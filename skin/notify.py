"""The notification card, on glass — and the square corner it removes.

THE DEFECT THIS FILE EXISTS TO FIX. The notify card shipped with a hook
(`skin.notify_run`) that always declined, so it was the only card in the
app with no glass presenter: overlay.NotifyCard._build_and_loop put it up
in a plain Tk window whose background is an opaque `CARD_BG` rectangle,
and `notify_card.flat()` filled that whole rectangle opaque and then drew
a ROUNDED OUTLINE inside it. The result is exactly what the owner
reported — "the corner is curved but there is something in the background
that makes them sharp". The curve was real; so was the square it was
painted on.

WHY THE FLAT TK CARD CANNOT ROUND ITS OWN CORNERS. It is not a missing
line of code, it is the toolkit:

  * Tk has no per-pixel alpha. A toplevel is opaque or, with
    `-alpha`, uniformly translucent — there is no channel in which the
    four corner pixels could be 0 and the middle 255.

  * `-transparentcolor` is a CHROMA KEY, not a mask. It punches out
    pixels that exactly equal one colour, so a corner Pillow antialiased
    into eight intermediate shades keeps seven of them: the card gets a
    fringe of the key colour instead of a hole. skin\\glass.py's header
    has the measurement — Tk antialiases nothing (0 intermediate shades
    in a 400x400 grab) and PIL antialiases everything, so a keyed window
    is either stair-cased or fringed, and there is no third setting.

So the corner cannot be cut where the picture is made. It has to be cut
where the picture is COMPOSITED, which on Windows means
UpdateLayeredWindow — skin\\glass.py — and that is what every other card
here (splash, dot, hint, review) already uses.

WHAT THIS FILE IS. skin\\review.py with the notify card's geometry: the
same Glass window with a hit test, the same shadow/frost/face/rim/hairline
recipe at the same offsets so the cards read as one family, and the same
ten-frames-a-second repaint — but only while there IS a clock bar to move,
which since 2026-09-04 is the exception rather than the rule: a
notification stays up until it is dismissed, so a column with no clock is
painted when the hover changes and not once more. The CONTENT is not
redrawn here at all —
`notify_card.compose()` already returns the whole card on a TRANSPARENT
ground, sized `notify_card.measure()`, precisely so a presenter can
composite it over a face of its own. `notify_card.flat()` is deliberately
NOT used on this path: flat() is the Tk fallback's opaque face, and
painting it here would put the square back.

DELETING skin\\ BRINGS THE SQUARE CORNERS BACK, ON PURPOSE. That is the
folder's whole promise (see skin\\__init__.py): the hook goes to None, the
Tk fallback in overlay.NotifyCard runs untouched, and the card is uglier
and completely functional. Nothing in overlay.py or notify_card.py was
changed to make this work.

Nothing here decides anything. A click on the × becomes
`card.pressed("dismiss")`, a click anywhere else becomes
`card.pressed("open")`, a drag becomes `card.placed(x, y)`, the clock
running out becomes `card.timed_out()` — what those MEAN is
overlay.NotifyCard's business and notify.py's.
"""
from __future__ import annotations

import logging
import queue
import time

import notify_card as nc
from PIL import Image
from .glass import DWM_RADIUS, Glass, primary_screen, virtual_screen
from .palette import BG, CARD, LINE, FG, argb

_log = logging.getLogger("app")

SHADOW = nc.SHADOW        # the room the window leaves round the card
RADIUS = nc.RADIUS
FACE_A = 202              # the face's alpha — skin\hint.py's glass weight
BLUR = 11
TICK_S = 0.03             # the loop; a click must feel immediate
REPAINT_S = 0.1           # the clock: ten frames a second is smooth enough
CACHE_MAX = 400           # text images kept across columns; a column of
                          # eight cards is under 100, so this is weeks of
                          # notifications before a trim, never a hover
_said = False             # the glass's kind is logged once per run
LATCH_S = 1.5             # a press with no new column after it this long
                          # frees the latch (see the loop)
CLICK_PX = 4              # a release that travelled less is a click, not a
                          # drag — overlay.NotifyCard._build_and_loop's rule
                          # and its constant, so the two paths agree on what
                          # a nudged mouse means


def _to_skia(img):
    import skia
    return skia.Image.frombytes(img.convert("RGBA").tobytes(), img.size,
                                skia.kRGBA_8888_ColorType)


def _frost(x: int, y: int, width: int, height: int):
    """What is behind the card, blurred. None if it cannot be had.

    THE FALLBACK SINCE 2026-10-18, not the frost. A photograph is out of
    date the moment it is taken: the owner moved a window and the card
    kept showing the one that had been there ("it takes time to update
    the background ... I want it live, so if I move a window behind it I
    see it going in behind"). The live blur is the compositor's
    (Glass.blur_behind); this is what a Windows that refuses that call
    still gets. Grabbed while the window exists but is not yet shown,
    which is the only moment the answer is the desktop rather than
    ourselves.
    """
    try:
        from PIL import ImageGrab, ImageFilter
        shot = ImageGrab.grab(bbox=(x, y, x + width, y + height),
                              all_screens=True)
        if shot.size != (width, height):
            shot = shot.resize((width, height))
        return shot.convert("RGBA").filter(ImageFilter.GaussianBlur(BLUR))
    except Exception:
        _log.debug("skin: no frost behind the notify card", exc_info=True)
        return None


# THERE USED TO BE A `_hide_from_capture` HERE, and it was deleted on
# 2026-09-04 at the owner's request, along with its one call site in
# `put_up`. What it did was set WDA_EXCLUDEFROMCAPTURE on the glass
# window, and the argument for it read well: overlay.NotifyCard promised
# to stay out of every screenshot, so the glass path had to keep the
# promise too or turning the skin on would quietly start burning
# notifications into the owner's pictures.
#
# The promise itself was the mistake. That flag is absolute — a window
# carrying it is invisible to EVERY grab on the machine, including the
# owner's own — so the card that says Claude has finished could not be
# photographed by the person it was for. He pressed Win+Shift+S and
# watched it vanish. "Screenshot" was never the thing to hide from;
# being in the way of the DRAG was.
#
# What replaces it is ordering, not a flag: capture.Controller._shot_flow
# freezes the desktop with one ImageGrab and hushes the cards on the very
# next line, so this card is in the frozen picture the selector paints
# and off the live screen before the selector maps. See the comment on
# that line in capture.py, and AGENTS.md's "our own windows and the
# owner's screenshots". The clip bar keeps the flag, because a recording
# has no single instant to freeze.


def face(canvas, width: int, height: int, scale: float, backdrop=None,
         x0: int = SHADOW, y0: int = SHADOW, radius: float | None = None,
         backdrop_at: tuple = (0, 0)) -> None:
    """The glass under the words: frost, face, rim, hairline — no shadow.

    skin\\review.py's recipe at the same offsets and the same alphas, on
    purpose — the review card and the notify card are the same object to
    the eye, one asked for and one arriving, and a second glass recipe
    would make them read as two apps. The one deliberate difference is
    the drop shadow, which this card does not have: see below.

    `width`/`height` are ONE CARD's, not the window's. `x0`/`y0` are where
    that card's top-left sits in the window and default to (SHADOW,
    SHADOW), which is the single-card case this file was written for; the
    column calls it once per card at the offsets notify_card.stack_layout
    hands out (2026-09-04), so every card in the pile is its own piece of
    glass with its own four rounded corners and the gaps between them stay
    holes. Every corner is an antialiased RRect on a canvas the caller
    cleared to 0x00000000, so the pixels outside the curve keep alpha 0 all
    the way to UpdateLayeredWindow — which is the entire fix. Nothing here
    ever draws a plain Rect; one would put the square straight back.

    The frost is drawn at `backdrop_at` — where the grab was taken,
    window-relative — under EVERY card's clip, on purpose: it is one grab
    of the whole window, so each card shows the part of the desktop that
    is actually behind it rather than a repeat of the top of the picture.
    With the live blur on there is no frost at all (`backdrop` None): the
    compositor draws what is behind, under this face, every frame.

    `radius` is the corner's, RADIUS at the scale by default; the
    Clear-all pill passes half its height and is a capsule.
    """
    import skia
    s = nc.clamp_scale(scale)
    rect = skia.Rect.MakeXYWH(x0, y0, width, height)
    radius = RADIUS * s if radius is None else float(radius)
    rrect = skia.RRect.MakeRectXY(rect, radius, radius)
    # NO DROP SHADOW, BY REQUEST (2026-09-04). This used to be six offset
    # round-rects with geometrically decaying alpha — boot.py's recipe,
    # drawn outside the face in the SHADOW margin — and the owner asked for
    # it gone: "I want without, only like the box, the message. Without the
    # shadow that it's outside the box." So the only thing this window
    # paints outside the curve now is nothing at all.
    #
    # The SHADOW margin itself STAYS, empty. It is transparent, the hit
    # test already hands it back to the desktop, and it is load-bearing
    # arithmetic everywhere else: notify_card.measure() sizes the window by
    # it, regions()/hit_test() are expressed in it, origin() subtracts it so
    # a dragged card is saved by the CARD's top-left rather than the
    # window's, and the position in [notify] x/y was written under that
    # rule. Reclaiming the 26 px would move a card the owner has already
    # placed, to buy back pixels nobody can see.
    # The frost, clipped to the rounded face with doAntiAlias=True. Without
    # that flag the clip is a hard 1-bit mask and the blurred desktop would
    # stair-case out to the corner of the image — a square edge again, made
    # of the backdrop this time instead of the face.
    if backdrop is not None:
        canvas.save()
        canvas.clipRRect(rrect, doAntiAlias=True)
        if not isinstance(backdrop, skia.Image):
            backdrop = _to_skia(backdrop)
        canvas.drawImage(backdrop, *backdrop_at)
        canvas.restore()
    # The face: a hair lighter at the top the way a surface lit from above
    # actually is, and translucent (FACE_A of 255) so the frost behind it
    # still reads as the desktop rather than as a texture.
    canvas.drawRRect(rrect, skia.Paint(
        AntiAlias=True, Dither=True,
        Shader=skia.GradientShader.MakeLinear(
            points=[(x0, y0), (x0, y0 + height)],
            colors=[argb(FACE_A, CARD), argb(FACE_A + 14, BG)],
            positions=[0.0, 1.0])))
    canvas.drawRRect(rrect, skia.Paint(
        AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0,
        Color=argb(180, LINE)))
    # A specular hairline on the top edge only, 60% of the width, fading at
    # both ends — the cheapest thing that says "glass". It stops well short
    # of the corners so it never fights the curve.
    canvas.drawLine(
        x0 + width * 0.20, y0 + 0.5, x0 + width * 0.80, y0 + 0.5,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style,
                   StrokeWidth=1.0,
                   Shader=skia.GradientShader.MakeLinear(
                       points=[(x0 + width * 0.20, y0),
                               (x0 + width * 0.80, y0)],
                       colors=[argb(0, FG), argb(64, FG), argb(0, FG)],
                       positions=[0.0, 0.5, 1.0])))


def run(card) -> None:
    """The body of overlay.NotifyCard's thread, with the picture swapped.

    The queue, `_alive`, `_closing` and the `_DONE` sentinel stay exactly
    where overlay.py put them, and every decision still belongs to
    overlay.NotifyCard: this only paints and reports. The window is built
    when the first card arrives and destroyed when the last one goes; in
    between, a column that changes — a card closed, a card arriving — is
    the SAME window resized and repainted in one flush (`put_up`,
    2026-10-18), because a rebuild left the screen empty for as long as it
    took and the owner saw every card blink out with the one he closed.

    IT IS A COLUMN NOW (2026-09-04). What arrives on the queue is a LIST
    of card dicts, newest first, and ONE window holds all of them: one
    face per card at the offset notify_card.stack_layout gives it, one
    compose() composited on top of each, one frost grab for the whole
    window, and one hit test that answers with the index of the card the
    pointer is on. The alternative — a window per card — would have meant
    N threads, N placements and gaps that drift apart the moment two of
    them repaint out of step.

    THE FOREGROUND. overlay.NotifyCard's Tk path reads `_foreground()`
    before it shows the window and hands the keyboard back with
    `_give_focus_back()` afterwards, because "Tk takes the foreground the
    moment it REALISES a window, and WS_EX_NOACTIVATE does not stop it"
    (AGENTS.md, measured 2026-08-26). There is nothing to give back here
    and so nothing to do: a Glass is a plain CreateWindowExW popup carrying
    WS_EX_NOACTIVATE and shown with SW_SHOWNOACTIVATE, so it never takes
    the foreground in the first place — no window between the two states,
    which is strictly better than taking it and returning it. skin\\hint.py
    and skin\\review.py are silent on this for the same reason.
    """
    import overlay

    glass = None
    shown = None                   # the LIST of card dicts on screen
    frost = None                   # the fallback's photograph, skia.Image
    frost_at = (0, 0)              # where on the screen it was taken
    live = False                   # the compositor blurs what is behind
    behind: list = []              # one blur window per piece of glass
    pieces: list = []              # their (x, y, w, h) in the column window
    hover = None                   # (index, what) or None
    caption = None                 # index of the card a drag started on
    cache: dict = {}
    deadline = None
    placed_at = (0, 0)             # where we last KNOW the window was put
    dismissing = False             # a click was already turned into a press
    latched_at = 0.0               # when it was, for LATCH_S below
    last_tick = time.monotonic()
    last_paint = 0.0
    dirty = False
    hushed = False                 # this loop's copy of card._hushed
    card._alive.set()

    def ident(index):
        """The id of the card at `index`, or None.

        None is what overlay.NotifyCard.pressed reads as "all" / "the
        newest", which is the honest answer to a click we could not pin on
        one card.
        """
        if shown is None or index is None or not 0 <= index < len(shown):
            return None
        return shown[index].get("id")

    def drop_behind():
        """Close every blur window. Before the column's own window when
        both go, so no blurred patch outlives the face it was under."""
        while behind:
            behind.pop().close()
        pieces.clear()
        card.behind = []

    def take_down():
        nonlocal glass, shown, frost, hover, deadline, dismissing, caption
        nonlocal live
        drop_behind()
        if glass is not None:
            glass.close()
            glass = None
        shown = None
        frost = None
        live = False
        hover = None
        caption = None
        deadline = None
        dismissing = False
        card.rect = None           # hovering() reads this; None means gone
        cache.clear()

    def on_hit(x, y):
        """Every pixel of the window, in window coordinates.

        notify_card.stack_hit_test answers HTCLIENT for a card's × box,
        HTCAPTION for the rest of that card (so Windows itself does the
        drag) and HTTRANSPARENT for the SHADOW margin AND FOR THE GAPS
        BETWEEN CARDS — which is what keeps a click aimed at the close
        button of a maximised window underneath landing on that close
        button. The column sits over the right edge of the screen, where
        scrollbars live, so this is not a hypothetical.

        It doubles as the hover tracker and as the record of WHICH card a
        drag is about to start on: WM_NCHITTEST arrives on every mouse move
        over the window, and it is the last message before DefWindowProc
        enters its modal move loop, so `caption` is still the card under
        the pointer when on_move runs. Leaving the column always crosses
        the shadow margin, so hover is cleared without needing a
        WM_MOUSELEAVE.
        """
        nonlocal hover, dirty, caption
        if shown is None:
            return nc.HTTRANSPARENT
        code, where = nc.stack_hit_test(shown, card.scale, x, y)
        want = where if code == nc.HTCLIENT else None
        if code == nc.HTCAPTION and where is not None:
            caption = where[0]
        if want != hover:
            hover = want
            dirty = True
        return code

    def on_move():
        """A press on the card's HTCAPTION area was let go.

        Windows sends this for a real drag AND for a click that never
        moved, because DefWindowProc enters its modal move loop on the
        first WM_NCLBUTTONDOWN either way — so this one callback has to
        tell the two apart, exactly as the Tk path's on_release does:
        travelled less than CLICK_PX, it is the OPEN — the whole card
        except the × means "take me to whoever sent this" (2026-09-04),
        and it is the card the press LANDED on that we name, which on_hit
        remembered on the way past; travelled more, it is where the owner
        wants the column from now on.

        The position is read back off the handle rather than remembered,
        because a drag by HTCAPTION is Windows moving the window and not
        us. SHADOW is added before it is reported: `placed` wants the
        corner the owner can SEE, and saving the window's corner instead is
        the bug that made every hint-card drag near the top of the screen
        snap back.

        `dismissing` is the latch. WM_EXITSIZEMOVE and WM_NCLBUTTONUP can
        both arrive for one release, and firing a press twice would mark a
        second, unseen notification as read — or raise a window twice.
        """
        nonlocal placed_at, dismissing, latched_at
        if glass is None or shown is None:
            return
        x, y = glass.where()
        if abs(x - placed_at[0]) + abs(y - placed_at[1]) < CLICK_PX:
            if dismissing:
                return
            target = ident(caption)
            if target == nc.PIN_ID:
                return             # a click on the pinned card's body is
                                   # nothing — and must not take the latch
            dismissing = True
            latched_at = time.monotonic()
            card.pressed("open", target)
            return
        placed_at = (x, y)
        card.placed(x + SHADOW, y + SHADOW)
        card.rect = (x + SHADOW, y + SHADOW,
                     x + glass.width - SHADOW, y + glass.height - SHADOW)

    def on_click(x, y):
        """A left click on an HTCLIENT pixel — a ×, the Clear-all pill, or
        the pinned card's own pill.

        The rest of the card is HTCAPTION and never reaches WM_LBUTTONDOWN
        at all; its click arrives through on_move above, and means the
        opposite thing. This road is the close buttons and only the close
        buttons: `pressed("dismiss")`, no window raised, nothing moved —
        one card's id for its ×, None ("all of them", the dismiss key's
        meaning) for Clear all.
        """
        nonlocal dismissing, latched_at
        if shown is None or dismissing:
            return
        code, where = nc.stack_hit_test(shown, card.scale, x, y)
        what = where[1] if where else None
        if code == nc.HTCLIENT and what == nc.DISMISS:
            dismissing = True
            latched_at = time.monotonic()
            card.pressed("dismiss", ident(where[0]))
        elif code == nc.HTCLIENT and what == nc.CLEAR:
            dismissing = True
            latched_at = time.monotonic()
            card.pressed("dismiss", None)
        elif code == nc.HTCLIENT and what == nc.BUTTON:
            # No latch: the pin is not taken down by this press, and a
            # second click while the screens come back is harmless.
            card.pressed("button", ident(where[0]))

    def paint(progress: float):
        """One frame: a face per piece of glass, painted fresh, each with
        its own content composited on it — the Clear-all pill when it is
        up, then the cards.

        `canvas.clear(0x00000000)` is what makes the corners a hole rather
        than black — the DIB behind a layered window is premultiplied BGRA
        and UpdateLayeredWindow reads its alpha per pixel, so anything the
        faces' RRects do not cover simply is not there. That is also what
        makes the GAPS between the cards real holes: nothing is drawn in
        them, so the desktop shows through and the column reads as a pile
        of separate cards rather than one long slab.
        """
        nonlocal last_paint, dirty
        if glass is None or shown is None:
            return
        canvas = glass.canvas
        canvas.clear(0x00000000)
        s = card.scale
        # where the fallback's photograph sits in THIS window: it was taken
        # where the window was then, and a column that has since grown or
        # shrunk has moved its top-left
        at = (frost_at[0] - glass.x, frost_at[1] - glass.y)
        # Over the live blur every corner is the COMPOSITOR'S: the blur
        # window under each piece is rounded by Windows at DWM_RADIUS and
        # by nothing else (see Glass.blur_behind), so a face drawn rounder
        # than that would leave a sliver of blur outside its own curve.
        corner = DWM_RADIUS if live else None
        pill = nc.clear_box(shown, s)
        if pill is not None:
            pw, ph = pill[2] - pill[0], pill[3] - pill[1]
            face(canvas, pw, ph, s, frost, pill[0], pill[1],
                 radius=corner if live else ph / 2, backdrop_at=at)
            canvas.drawImage(_to_skia(nc.compose_clear(
                shown, s, hover == (None, nc.CLEAR), cache)), pill[0], pill[1])
        for index, (x, y, w, h) in enumerate(nc.stack_layout(shown, s)):
            face(canvas, w, h, s, frost, x, y, radius=corner,
                 backdrop_at=at)
            # compose(), never flat(): flat() is the Tk fallback's OPAQUE
            # face with the same content on top, and drawing it here would
            # paint a solid CARD rectangle over the rounded glass — the
            # exact defect this module exists to remove.
            what = hover[1] if (hover and hover[0] == index) else None
            content = nc.compose(shown[index], s, progress, what, cache)
            canvas.drawImage(_to_skia(content), x, y)
        glass.flush()
        last_paint = time.monotonic()
        dirty = False

    def progress_now() -> float:
        """The clock's fill right now: 1.0 with no clock, which is the
        default since 2026-09-04."""
        seconds = float(shown[0].get("seconds") or 0) if shown else 0.0
        if deadline is None or seconds <= 0:
            return 1.0
        return max(0.0, min(1.0, (deadline - time.monotonic()) / seconds))

    def restart_clock():
        nonlocal deadline
        # ONE clock for the column, read off the newest card. Every card in
        # a column carries the same `seconds` (NotifyCard.show builds them
        # all with its own), and the default has been 0 since 2026-09-04,
        # which means no clock at all.
        seconds = float(shown[0].get("seconds") or 0) if shown else 0.0
        deadline = (time.monotonic() + seconds) if seconds > 0 else None

    def place(items):
        """(x, y, width, height) of the window that holds `items`.

        primary for the corners, the whole desktop for a saved position:
        a card left on a second screen belongs on that second screen.
        `inset=SHADOW` is how NotifyCard.origin knows the window is bigger
        than the card, so mid-height on the right edge is the CARD's right
        edge and not the shadow's — and under the default bottom anchor
        a column of a new height keeps its bottom edge where it was.
        """
        s = nc.clamp_scale(card.scale)
        win_w, win_h = nc.stack_measure(items, s)
        x, y = card.origin(win_w, win_h, primary_screen(), SHADOW,
                           virtual_screen())
        return x, y, win_w, win_h

    def new_behind(x, y, w, h):
        """One blur window: click-through, never focused, exactly the size
        of its piece, rounded by Windows, the compositor's blur behind it
        and nothing of its own in it. None when Windows will not give it
        both the blur and the corner — a square blur is the frame again."""
        b = Glass(x, y, w, h, gpu=False)
        if not (b.round_corners() and b.blur_behind()):
            b.close()
            return None
        b.present(Image.new("RGBA", (w, h), (0, 0, 0, 0)))
        return b

    def follow():
        """The column moved — every step of a drag Windows runs for it —
        and the blur windows go with it, so the glass never slides off its
        face. Asked on WM_MOVE, so it must stay cheap: the offsets are
        `pieces`, worked out when the column last changed."""
        if glass is None or not behind:
            return
        gx, gy = glass.where()
        for b, (x, y, _w, _h) in zip(behind, pieces):
            b.place(gx + x, gy + y)

    def sync_behind(show: bool) -> bool:
        """One blur window per piece of glass — the Clear-all pill and
        every card — each its piece's size, at its piece's place on the
        screen, directly under the column's own window. Windows are kept
        and moved rather than built again when the column changes; extra
        ones close. False when a new one could not be made live, and then
        none are left: the column goes on with a photograph instead."""
        nonlocal live
        if glass is None or shown is None or not live:
            return False
        want = [(int(x), int(y), int(w), int(h))
                for x, y, w, h, _r in nc.stack_shapes(shown, card.scale)]
        gx, gy = glass.x, glass.y
        while len(behind) > len(want):
            behind.pop().close()
        for i, (x, y, w, h) in enumerate(want):
            if i < len(behind):
                b = behind[i]
                b.resize(w, h)
                b.move(gx + x, gy + y)
                b.present(Image.new("RGBA", (w, h), (0, 0, 0, 0)))
            else:
                b = new_behind(gx + x, gy + y, w, h)
                if b is None:
                    drop_behind()
                    live = False
                    return False
                behind.append(b)
            if show:
                b.show()
            b.under(glass.hwnd)
        pieces[:] = want
        card.behind = [int(b.hwnd) for b in behind]
        return True

    def put_up(items):
        """A new column. Onto the window that is already up when there is
        one — resized, moved, repainted, all in the one
        UpdateLayeredWindow, so nothing on screen goes away first.

        THE OWNER'S BUG, 2026-10-18: "when I close one, all the cards
        vanish for a second and then all of them come back without the
        one I closed". Every change used to be `take_down()` and a new
        window: the glass closed, the text cache thrown away and every
        string drawn again through DrawTextW, the desktop photographed
        and blurred again, a GPU surface allocated — a gap the length of
        all of that, with nothing on screen. Now only the first card of a
        column builds a window, and the last one going takes it down.
        """
        nonlocal shown, hover, dismissing, caption
        items = list(items)
        if glass is not None and not hushed:
            if items == shown:
                return             # the engine re-saying what is up
            shown = items
            hover = None
            caption = None
            dismissing = False
            restart_clock()
            try:
                relayout()
            except Exception:
                _log.info("skin: the notify column would not relayout; "
                          "building it again", exc_info=True)
                take_down()
                shown = items
                restart_clock()
                map_card()
            return
        take_down()
        shown = items
        hover = None
        caption = None
        dismissing = False
        restart_clock()
        if hushed:
            # A NOTIFICATION LANDING MID-SELECTION, which is the case the
            # hush exists for. The item is accepted and its clock is
            # already waiting (see the loop), but no window is built: this
            # one is topmost and would map straight over the screenshot
            # selector and swallow the owner's drag. `map_card` builds it
            # the moment the screen is his again.
            return
        map_card()

    def relayout():
        """The window that is up, made the shape of `shown` in place: same
        handle, new size and position and picture in one flush, then the
        region. The text cache is kept — the strings of the cards that
        stayed are the same strings — and only trimmed when it has grown
        past what any column could need."""
        nonlocal placed_at
        if len(cache) > CACHE_MAX:
            cache.clear()
        x, y, win_w, win_h = place(shown)
        glass.resize(win_w, win_h)
        glass.move(x, y)
        placed_at = (x, y)
        paint(progress_now())
        if live and not sync_behind(show=True):
            paint(progress_now())  # back to the photograph's rounder face
        card.rect = (x + SHADOW, y + SHADOW, x + win_w - SHADOW,
                     y + win_h - SHADOW)

    def map_card():
        """Build the glass for the whole column and put it on screen.

        Split out of `put_up` on 2026-09-04 so a hush can hold a card
        without losing it: `put_up` decides WHAT is on screen, this
        decides WHEN, and the two are no longer the same moment.
        """
        global _said
        nonlocal glass, frost, frost_at, placed_at, live
        item = shown
        if not item or glass is not None:
            return
        x, y, win_w, win_h = place(item)
        glass = Glass(x, y, win_w, win_h, hit=on_hit, moved=on_move,
                      clicked=on_click, moving=follow)
        # NO `_hide_from_capture(glass.hwnd)` HERE ANY MORE — removed
        # 2026-09-04, at the owner's request, because the card announcing
        # that Claude had finished could not be photographed by the person
        # it was announcing to. See the block where that helper used to
        # live, above `face`, for the whole argument.
        # The blur is never on THIS window: on a window this size it would
        # fill the margin and the gaps between the cards too — the dark
        # frame the owner circled on 2026-10-19 — because the compositor
        # cuts its blur to nothing but its own rounded corner. It goes on
        # one window per card, under this one (sync_behind).
        live = True
        live = sync_behind(show=False)
        if live:
            frost = None
        else:
            # the window exists and is not shown yet, so the grab is the
            # desktop and not ourselves
            shot = _frost(x, y, win_w, win_h)
            frost = _to_skia(shot) if shot is not None else None
            frost_at = (x, y)
        if not _said:
            _said = True
            _log.info("skin: the notify column's glass is %s",
                      "live (the compositor's blur)" if live
                      else "a photograph (no blur behind on this Windows)")
        placed_at = (x, y)
        # Painted BEFORE it is shown, so the card is never on screen for
        # even one frame as an empty layer. The progress is computed
        # rather than assumed to be 1.0: coming back from a hush, the card
        # resumes with the seconds it went down with.
        paint(progress_now())
        for b in behind:
            b.show()
        glass.show()
        glass.raise_()
        for b in behind:
            b.under(glass.hwnd)
        card.rect = (x + SHADOW, y + SHADOW, x + win_w - SHADOW,
                     y + win_h - SHADOW)

    def set_hushed(on: bool):
        """Obey `card._hushed`, on this thread and nowhere else.

        The caller — capture's screenshot flow, from the keyboard hook —
        only set an Event. Every window call is here, because Glass is as
        thread-bound as Tk is.
        """
        nonlocal hushed, glass, frost, hover, dismissing, live
        if on == hushed:
            return
        hushed = on
        if on:
            drop_behind()
            if glass is not None:
                glass.close()
                glass = None
            frost = None
            live = False
            hover = None
            dismissing = False
            # hovering() reads this; None means the card is not under the
            # pointer, which is true — it is not on screen at all.
            card.rect = None
            cache.clear()
        else:
            map_card()

    try:
        while not card._closing.is_set():
            try:
                while True:
                    item = card._q.get_nowait()
                    if item is overlay._DONE:
                        card._closing.set()
                        break
                    if item is None:
                        take_down()
                    else:
                        put_up(item)
            except queue.Empty:
                pass
            if card._closing.is_set():
                break
            # AFTER the queue, so a card that arrived in this same tick is
            # already in `shown` and gets held rather than built.
            set_hushed(card._hushed.is_set())
            now = time.monotonic()
            dt, last_tick = now - last_tick, now
            if dismissing and now - latched_at > LATCH_S:
                # The latch is let go by the next column (put_up); if none
                # comes — an engine that never answered a press — a card
                # must not stay deaf to its own × for good.
                dismissing = False
            if shown is not None and hushed and deadline is not None:
                # Down for somebody's selection: the clock waits, exactly
                # as it waits under the pointer below. Seconds spent off
                # the screen are not seconds the owner had the card.
                deadline += dt
            if shown is not None and glass is not None:
                seconds = float(shown[0].get("seconds") or 0) if shown else 0.0
                progress = 1.0
                if deadline is not None:
                    # The clock stops under the pointer, so a card somebody
                    # is reading cannot vanish mid-sentence. `hovering()` is
                    # a rect and a cursor position, no window handle, which
                    # is why it is cheap enough to ask every tick.
                    if card.hovering():
                        deadline += dt
                    left = deadline - now
                    if left <= 0:
                        # Running out is NOT a dismissal: timed_out() leaves
                        # the item unread and notify.py's reminders bring it
                        # back. Only a click, or Esc over the card, marks it
                        # seen.
                        card.timed_out()
                        take_down()
                        time.sleep(TICK_S)
                        continue
                    progress = left / seconds if seconds > 0 else 1.0
                # A clockless column (the default since 2026-09-04) has
                # nothing that changes on its own, so it is painted when
                # the hit test says the hover moved and never otherwise.
                if dirty or (deadline is not None
                             and now - last_paint >= REPAINT_S):
                    paint(progress)
                glass.pump()
            time.sleep(TICK_S)
    except Exception:
        _log.info("skin notify card stopped early", exc_info=True)
    finally:
        take_down()
        card._closing.set()


__all__ = ["face", "run"]
