"""Pictures: one you drag, one you take, and a clip you can send.

Three keys, one folder. **ctrl+f11** freezes the screen and dims it, you
drag a rectangle (or hold Shift and lasso a shape) and let go: the picture
is on your clipboard and in `captures\\` before you have moved your hand,
and a glass toolbar opens under the selection so you can crop it, draw on
it, arrow at it or blur the part nobody else should read. **ctrl+f12**
picks a region the same way — or a whole monitor, by name, off a chip — and
records it to an mp4 until you tap the key again, announcing itself in a
corner and then shrinking to a red dot and a clock. **ctrl+f6** opens the
WEBCAM in a card in the middle of the screen with a shutter under it, and
the photo it takes lands in the same folder, on the same clipboard, in the
same editor, laid on the screen exactly where the preview was.

It is Win+Shift+S, plus the editor, plus a recorder, plus a camera, written
to the same rules as the rest of this app: nothing leaves the machine,
everything is measured, and the pixels are yours.

WHY THIS IS ITS OWN MODULE AND NOT PART OF visual_qa.py
--------------------------------------------------------
They look alike for the first 200 ms and then stop. The ask card's
selection is a crop on its way to a model: it dies with the window, it is
never written down, and its whole life is one question. A capture is the
opposite — it is a FILE, it outlives the window, and the interesting part
starts after the drag. So the selection gesture is deliberately the same
(the owner asked for the lasso here because he already has it there), and
everything after the mouse comes up is not.

What IS shared is imported rather than re-typed: `visual_qa` owns the
liquid-glass painter, the bidi text renderer, the icon set and the palette,
and this module calls them. A second copy of `glass_plate` would be a
second copy that drifts.

MEASURED ON THIS MACHINE, 2026-08-25 (live, not catalog)
---------------------------------------------------------
CAPTURE. A reused DIB section + BitBlt beats PIL's ImageGrab by 5x, and
that gap is the whole reason a recorder is possible here at all:

    region        BitBlt+DIB    PIL ImageGrab
    1280x720         10.1 ms         53.7 ms
    1920x1080        11.6 ms         56.7 ms
    2560x1440        21.7 ms         56.7 ms

ImageGrab's cost is nearly flat because it builds its DCs and its bitmap
per call; ours are built once and reused for the whole clip. Add the
cursor draw and the copy out of the shared buffer and one recorder frame
is 9.5 ms at 720p, 18.1 ms at 1080p, 32.3 ms at 1440p. CAPTUREBLT (which
is what makes layered windows appear) costs about 1 ms of that and is
kept.

ENCODE, libx264 through PyAV — already installed, as faster-whisper's own
dependency, so the recorder adds NO new package and no ffmpeg.exe:

    preset veryfast, tune zerolatency, crf 23
    720p   5.1-5.7 ms/frame     1080p  11.6 ms      1440p  20.9 ms
    h264_nvenc p4 was the same speed warm (15.1 ms at 1440p) and spiked
    to 234 ms on its first frame while the encoder session came up. The
    spike is a dropped frame at the exact moment the user is watching,
    and the GPU is already carrying two Whisper models and gemma3, so
    libx264 wins on both counts.

END TO END, capture thread + encode thread over a bounded queue:
    720p  30 fps -> 30.0 fps achieved, 0 frames dropped
    1080p 30 fps -> 30.0 fps achieved, 0 frames dropped
    1440p 30 fps -> 28.0 fps achieved, 0 frames dropped
The 1440p shortfall is the grab, not the encoder. It does not speed the
video up, because every frame carries a WALL-CLOCK presentation stamp in
a 1/1000 timebase rather than a frame number: a clip that averaged 28 fps
is 28 fps of real seconds, and the 4.0 s probe came back as 4.026 s.

CLIPBOARD. Encoding a 640x360 shot to both formats costs 43 ms (nearly
all of it the BMP pass for CF_DIB); the clipboard write itself is 0.4 ms.
We set CF_DIB and the registered "PNG" format and Windows synthesises
CF_BITMAP and CF_DIBV5 from the first — so Paint, Word, Chrome and Slack
all find something they like, and the PNG keeps the alpha a lasso leaves.

THE CONTROLS DO NOT APPEAR IN THE RECORDING, and that is an API, not luck.
`SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` on the clip bar
and on the region frame hides them from BitBlt with and without CAPTUREBLT
and from PIL's ImageGrab as well — measured 0 of 60000 pixels where a
saturated magenta window demonstrably was. Without it the only safe
placement would be outside the recorded region, which is no placement at
all when the region is the whole screen.

TRAPS PAID FOR HERE
--------------------
- **Every GDI call that touches a HANDLE needs argtypes.** ctypes defaults
  an argument to c_int, and a 64-bit HBITMAP does not fit in one: the
  first version of the recorder died on `DeleteObject(ii.hbmColor)` with
  "int too long to convert" after every frame it had already captured
  correctly. They are declared once, at import, in `_declare()`.
- **A tk.Frame is an opaque rectangle, forever** (AGENTS.md). The editor
  can be glass because the screen is FROZEN and we own the pixels behind
  the toolbar. The clip bar CANNOT: it floats over a screen that is still
  moving, so it is honest opaque card stock with `SetWindowRgn` corners,
  the same shape popup.py uses. Do not try to make it glass — there is
  nothing to blur.
- **Never grab the screen back to read your own ink.** The same rule
  visual_qa records: it races the topmost window and returns black. Every
  mark lives as POINTS in Python and is replayed into the pristine crop
  with Pillow; the canvas item under the pointer is only there for the
  live feel and is deleted the moment the stroke commits.
- **ImageDraw's `fill` REPLACES pixels, it does not blend them.** The
  highlighter and the blur box are built as their own RGBA layers and
  composited, or they punch a hole through the screenshot.
- **A Tk window must be COLLECTED by the thread that built it.** The full
  Tcl_AsyncDelete story is in AGENTS.md and visual_qa.py; the shape of the
  answer here is the same — each flow runs `gc.collect()` in a `finally`
  once the window is unreachable, on the thread that built it. The corner
  cards are the one thing that outlive their flow, and they answer the
  same rule the other way round: ONE interpreter, built and pumped and
  buried by one long-lived thread (`ShotCards`), with every card a
  Toplevel on it. A root that never dies is a `Tcl_DeleteInterp` that
  never runs, on any thread.
- **`_busy` means "a window that OWNS THE SCREEN is up"** — the selector,
  the editor, the camera, the clip bar — and NOT "a capture flow is
  running". It stopped meaning the second thing when the corner cards
  started stacking: a card is a small thing in a corner that leaves the
  screen and the screenshot key alone, so holding the flag across it made
  the key dead for five seconds after every capture, which is exactly the
  thing being fixed. `Controller._take_screen` is the only way to claim
  it and `_free_screen` the only way to let it go.
- **h264 wants even dimensions.** yuv420p subsamples chroma by two, so an
  odd-width region is a libx264 error at `container.add_stream` time, long
  after the user has started recording. `even_box` shrinks the rectangle
  by a pixel before anything is opened.

THE CAMERA, AND WHY IT LIVES HERE
----------------------------------
Because everything after the shutter is already written. A photo wants the
same folder, the same clipboard formats, the same crop-draw-blur-ask
toolbar and the same "it is saved before you can lose it" promise — and a
second module would be a second copy of all of it, drifting. What is new
is the front of it: enumerate DirectShow's video devices, open one, show
the frames, and turn one of them into the picture the rest of this file
already knows how to handle. `Camera` is the device, `CameraWindow` is the
card, `Controller.begin_photo` is the key, and `ShotWindow(start_box=...)`
is the join — the editor cannot tell which lens a picture came through,
and that is the point.

Two rules the camera half is built on, and both of them are "no
divergence":

- **What you see is what you get.** ONE image per frame, made at the size
  the window shows, and that image is the preview AND the file AND what
  the editor opens on. So `preview_fit` may make the picture smaller than
  the camera could have managed (1:1 whenever it fits, which it does at
  1280x720 on this desk), and `mirror` flips both or neither. A preview
  that disagreed with the file it produced would be the same bug
  `render_shot` exists to prevent, wearing a lens.
- **The lens closes at the shutter, not at the end.** `Camera.close()` is
  called by `_fire`, before the flash, before the save, long before the
  editor. The light beside the camera means what it looks like it means.

MEASURED, 2026-08-26, live, on an eMeet C960 over USB:
    open -> first frame        654-829 ms over six opens
    delivered                   25 fps at 1280x720 mjpeg (40.1 ms apart,
                                steady to a tenth of a millisecond)
    one frame to the window      5.4 ms at 800x450 · 4.3 ms at 1280x720
    listing the devices        147 ms
ASK FOR MJPEG. This camera offers 1920x1080 at 30 fps as mjpeg and the
SAME size at 5 fps as raw yuyv422, and DirectShow hands over the raw one
unless it is told otherwise. Measured off the device's own list_options,
both pins.

PRIVACY, stated plainly because it decides the defaults
--------------------------------------------------------
Unlike the ask card — which holds its screenshot in memory and never
writes it down — this feature's whole job is to write it down. So the
folder is treated the way transcripts.log is: it lives beside the app, it
is gitignored, and nothing in it is ever uploaded anywhere by this module.
There is no cloud path in this file at all; the only way a capture reaches
a model is the Ask button, which hands the pixels to visual_qa and obeys
`visual_qa.allow_screenshot_upload` like every other question.

The camera is the sharper end of that. Nothing in this app opens it but
`ctrl+f6`, it is open only while the card is up, and it is released the
instant the shutter fires rather than when the editor closes. `[camera]
enabled = false` unregisters the key, and then nothing here can open it
at all.

The microphone is OFF by default in a recording (`[capture] audio =
"off"`) and there is a switch on the clip bar to turn it on for the clip
you are recording. A screen recorder that quietly opens the mic is a
surprise, and this app's rule is that audio does not travel — a recording
you make on purpose is you choosing otherwise, once, visibly.
"""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as w
import gc
import io
import logging
import math
import os
import queue
import threading
import time
from pathlib import Path

log = logging.getLogger("app")

# visual_qa owns the paint. Importing it costs nothing: like this module it
# keeps Pillow and tkinter inside the functions that need them, so main.py
# can build a Controller at startup without paying for either.
import visual_qa as _vq

from visual_qa import (              # noqa: F401  (re-exported on purpose)
    ACCENT, CARD, CARD_HI, DIM, FAINT, FG, GLASS_TINT, INK, INK_DIM,
    INK_FAINT, LINE, MARK, PANE, SELECT_BG, STROKE,
    normalize_bbox, selection_readout, virtual_screen, work_area_near,
)

_TICK_S = _vq._TICK_S
_FREEZE_LUT = _vq._FREEZE_LUT

# ------------------------------------------------------------------ knobs

# The annotation palette. RED first because that is what an arrow on a
# screenshot has meant since before any of us: the mark has to be the one
# thing on the picture that could not possibly be part of it. MARK (the
# ask card's warm yellow) is second so the two features share an ink.
INKS = (
    ("red", (224, 53, 43)),
    ("yellow", MARK),
    ("blue", (86, 156, 245)),
    ("white", (245, 249, 255)),
)
PEN_W = 3                    # px, the freehand and the arrow
BOX_W = 3                    # px, the rectangle outline
HIGHLIGHT_W = 18             # px, and translucent — a marker, not a pen
HIGHLIGHT_A = 92

# THE INK IS OVERSAMPLED. Pillow antialiases nothing, so a diagonal drawn
# straight onto the picture is a staircase — see ink_scale for the whole
# argument and the measurements. 4x where it fits, less on a mark whose
# rectangle is most of a 1440p screen.
INK_SS = 4
INK_SS_BUDGET = 4_000_000    # px in one oversampled layer, ~16 MB RGBA
ARROW_HEAD = 6.5             # head length, as a multiple of the stroke.
                             # An arrow on a screenshot is not a diagram's
                             # arrow: it is the one thing on the picture
                             # that must be seen before anything else, so
                             # the head is deliberately heavier than the
                             # geometry would suggest
ARROW_HEAD_MIN = 16          # px, so a hairline arrow still has a point
ARROW_SPREAD = 27            # degrees off the shaft to each barb
ARROW_NOTCH = 0.62           # how far back the notch sits, of the head
# How far each kind of mark can paint outside the points it is made of.
_MARK_PAD = {"pen": PEN_W + 2, "arrow": 44, "box": BOX_W + 3,
             "highlight": HIGHLIGHT_W + 2}
PIXEL_BLOCK = 12             # the redaction mosaic; below ~8 px, 12 pt
                             # text is still readable in the blocks

# The toolbar. One row of round chips and pill buttons, one line of text.
CHIP = 34
GAP = 7
BAR_PAD_X, BAR_PAD_Y = 14, 12
BAR_H = 82
BAR_RADIUS = 22
BAR_GAP = 18                 # between the selection and the toolbar

# The hint card the selector opens with: one sheet of glass holding the
# instructions and a tile per monitor. Glass rather than card stock,
# because at this moment the screen is frozen and we own the pixels
# behind it — the same reason the editor's toolbar can be glass and the
# clip bar cannot.
HINT_PAD = 18
HINT_RADIUS = 20
CHIP_W, CHIP_H = 134, 72
CHIP_GAP = 10
CROP_BACK = 0.42             # how far the area you already cut away is
                             # brought back toward its real pixels while
                             # the crop tool is up. Not all the way: it
                             # has to be obviously reachable and just as
                             # obviously not part of the picture yet

# The clip bar, which is NOT glass (see the module docstring).
# The clip bar has three shapes and one window. It ANNOUNCES itself the
# way a recorder should — the shape NVIDIA's overlay uses, because that is
# the shape the owner asked for — and then gets out of the way as a small
# corner pill that is only a red dot and a clock. Hovering it brings the
# controls back.
ANNOUNCE_W, ANNOUNCE_H = 344, 58
ANNOUNCE_S = 2.6             # how long "Recording started" stays up
TIMER_H = 34
BAR_BTN = 30
CLIP_BAR_RADIUS = 14
TIMER_RADIUS = TIMER_H // 2
CORNER_MARGIN = 18           # from the WORK area, so never under a taskbar
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right", "off")
CLIP_FRAME_W = 3             # the marching border around what is recorded

FLASH_MS = 1400              # popup.py's confirmation dwell, same number
TOAST_MS = 7000              # how long "saved" stays up on its own

# The card a CAPTURE leaves in the corner instead of opening an editor over
# the whole screen. See ShotToast for why that trade is the right way round.
TOAST_W, TOAST_H = 384, 96
TOAST_THUMB = (112, 72)
TOAST_TEXT_X = 136

# THE CARDS STACK, so two more numbers: the air between them, and a
# ceiling `capture.toast_stack` is validated against. The ceiling is not
# taste — every card holds a frozen copy of the whole desktop so the
# editor can still open on the pixels as they WERE, and on this machine
# (3 monitors, 2026-09-03) that is about 18 MB apiece.
TOAST_GAP = 10               # between stacked cards
TOAST_STACK_MAX = 8          # the ceiling toast_stack is validated against

# 1/1000 s. Wall-clock presentation stamps rather than frame numbers, so a
# clip that could only manage 24 fps plays at real speed instead of fast.
CLOCK_HZ = 1000


# THE LENS. The camera window is not glass either, and for the same reason
# the clip bar is not: there is nothing frozen behind it to photograph. It
# is card stock with SetWindowRgn corners and the live picture sits in it
# as a plain inset rectangle — a rounded mask over a preview is a mask
# recomputed thirty times a second for a corner nobody looks at.
CAM_PAD = 14                 # card edge to picture
CAM_STRIP_H = 76             # the control row under it
CAM_RADIUS = 18
CAM_CHIP = 34
CAM_MIN_W = 300              # the card never narrower than its own controls.
                             # preview_fit never upscales, so a 160x120
                             # webcam would otherwise make a card too narrow
                             # for the shutter to sit between the chips
SHUTTER = 54                 # the round button, the biggest thing on the row
CAM_TIMERS = (0, 3, 10)      # what the timer chip cycles through, seconds
CAM_FLASH_MS = 150           # the white blink that says the shutter fired
CAM_WAKE_S = 6.0             # stop waiting for a first frame after this.
                             # Measured 654-829 ms on this machine over six
                             # opens, so six seconds is not a budget, it is
                             # the line past which the device is not coming
CAM_HOLD_MS = 900            # how long the window stays up after a shot
                             # when the editor is switched off, so the
                             # filename can be read


class CaptureError(Exception):
    """Something the user has to be told about, in one sentence."""


# ------------------------------------------------------------ pure helpers
# Numbers in, numbers out. Everything here is testable without a screen,
# a GPU or a file, and there is a test that says so.

def even_box(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Shrink a rectangle to even width and height.

    yuv420p subsamples chroma 2x2, so libx264 refuses an odd side — and it
    refuses it at add_stream() time, which is after the user has chosen a
    region and expects to be recording. One pixel off the right and the
    bottom is invisible and cannot fail.
    """
    left, top, right, bottom = normalize_bbox(*bbox)
    width, height = right - left, bottom - top
    return (left, top, left + width - (width % 2), top + height - (height % 2))


def clamp_box(bbox: tuple[int, int, int, int],
              bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """A rectangle pushed back inside `bounds` (left, top, right, bottom).

    A drag that ran off the edge of the desktop is a legal drag; a BitBlt
    that starts outside the screen is undefined, and PIL's crop pads it
    with black. Both are fixed here rather than at four call sites.
    """
    left, top, right, bottom = normalize_bbox(*bbox)
    bl, bt, br, bb = bounds
    left, top = max(left, bl), max(top, bt)
    right, bottom = min(right, br), min(bottom, bb)
    return (left, top, max(left, right), max(top, bottom))


def monitor_near(x: int, y: int) -> tuple[int, int, int, int]:
    """The WHOLE monitor under (x, y) — taskbar included, unlike
    work_area_near.

    This is what Enter means in the selector: "this screen", and a
    screenshot of a screen includes its taskbar. work_area_near is for
    placing windows, which must not sit under it.
    """
    user32 = _user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT),
                    ("rcWork", w.RECT), ("dwFlags", w.DWORD)]

    point = w.POINT(int(x), int(y))
    monitor = user32.MonitorFromPoint(point, 2)     # DEFAULTTONEAREST
    monitor = ctypes.c_void_p(monitor) if monitor else None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor is None or not user32.GetMonitorInfoW(
            monitor, ctypes.byref(info)):
        vx, vy, vw, vh = virtual_screen()
        return (vx, vy, vx + vw, vy + vh)
    rc = info.rcMonitor
    return (rc.left, rc.top, rc.right, rc.bottom)


def monitors() -> list[dict]:
    """Every monitor: primary first, then left to right.

    `virtual_screen()` answers "how big is the desktop" and that is a
    different question from "which screens are there" — this machine's
    desktop is one 4480x1440 rectangle made of two monitors, and "record
    the screen" has to mean one of them. Each entry is
    {"rect": (l, t, r, b), "primary": bool, "label": "Screen 1"}.

    EnumDisplayMonitors, not the registry and not Tk: it is the only source
    that agrees with the coordinates every other call in this module uses,
    including the negative ones the left monitor lives at.
    """

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT),
                    ("rcWork", w.RECT), ("dwFlags", w.DWORD)]

    found: list[dict] = []

    @_MONITORENUMPROC
    def collect(handle, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if _user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            rc = info.rcMonitor
            found.append({"rect": (rc.left, rc.top, rc.right, rc.bottom),
                          "primary": bool(info.dwFlags & 1)})
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, collect, 0)
    except Exception:
        log.debug("could not enumerate the monitors", exc_info=True)
    if not found:
        vx, vy, vw, vh = virtual_screen()
        found = [{"rect": (vx, vy, vx + vw, vy + vh), "primary": True}]
    found.sort(key=lambda m: (not m["primary"], m["rect"][0], m["rect"][1]))
    for i, entry in enumerate(found, 1):
        entry["label"] = f"Screen {i}"
    return found


def corner_at(box: tuple[int, int, int, int], size: tuple[int, int],
              corner: str, margin: int = CORNER_MARGIN) -> tuple[int, int]:
    """Top-left position for a `size` window in a `corner` of `box`.

    The recording indicator is anchored to a CORNER rather than placed
    beside the region, and that is the whole difference between an
    indicator and an obstruction: a corner is somewhere you can learn to
    glance at, and it does not move when the thing being recorded does.
    `box` should be a WORK area, so the bottom corners are not under the
    taskbar.
    """
    left, top, right, bottom = box
    width, height = size
    x = left + margin if corner.endswith("left") else right - width - margin
    y = top + margin if corner.startswith("top") else bottom - height - margin
    return (x, y)


def stack_fits(box: tuple[int, int, int, int], size: tuple[int, int],
               margin: int = CORNER_MARGIN, gap: int = TOAST_GAP) -> int:
    """How many cards this WORK area can hold in one column.

    THIS IS THE CEILING THE SCREEN IMPOSES, not the one the owner chose.
    `capture.toast_stack` is a preference; this is arithmetic, and the
    smaller of the two is what actually goes up. A column taller than the
    work area would push the oldest card off the top of it, where it is
    neither readable nor clickable — and a card you cannot reach is worse
    than one that was never offered, because it still costs the memory of
    a frozen screen.

    The margin is paid twice (once at each end) and the gap is paid
    between cards but not after the last one, which is what the `+ gap`
    is doing: n cards need `n * height + (n - 1) * gap`.

    At least one, always. A work area too short for a single card is not
    a reason to show nothing — it is a reason to show the one card that
    matters, which is the newest.
    """
    left, top, right, bottom = box
    width, height = size
    return max(1, (bottom - top - 2 * margin + gap) // (height + gap))


def stack_at(box: tuple[int, int, int, int], size: tuple[int, int],
             corner: str, index: int, count: int,
             margin: int = CORNER_MARGIN,
             gap: int = TOAST_GAP) -> tuple[int, int]:
    """Top-left for card `index` of `count`, OLDEST FIRST.

    OLDEST AT THE TOP AND NEWEST AT THE BOTTOM, in all four corners. That
    is the order a stack of paper lands in and the order every notifier
    on this desk already uses, so it is the one the hand expects: the card
    that is about to go is the one furthest from where the next one will
    appear, and nothing you were reading jumps sideways when one arrives.

    Which means the two families of corner anchor from OPPOSITE ENDS. A
    top corner pins the OLDEST at the margin and hangs the rest below it;
    a bottom corner pins the NEWEST at the margin and stacks the rest
    above it. Anchoring both from the oldest would make a bottom-corner
    stack grow down into the taskbar, and anchoring both from the newest
    would make a top-corner stack grow up off the screen.

    Reduces to `corner_at` exactly when `count == 1`, which is what keeps
    `toast_stack = 1` looking precisely like the card that shipped before
    any of this existed.
    """
    x, y = corner_at(box, size, corner, margin)
    step = size[1] + gap
    if corner.startswith("top"):
        y += index * step
    else:
        y -= (count - 1 - index) * step
    return (x, y)


def stack_layout(anchors, size: tuple[int, int], corner: str,
                 margin: int = CORNER_MARGIN,
                 gap: int = TOAST_GAP) -> list[tuple[int, int]]:
    """One (x, y) per card, oldest first.

    `anchors` is each card's OWN WORK AREA — the one `ShotToast` already
    picks from the middle of the capture, so a shot dragged on the left
    monitor leaves its card on the left monitor. Two monitors therefore
    mean two INDEPENDENT COLUMNS, each numbered from its own oldest, and
    that is the whole reason this is not a single `enumerate`: a card on
    the other screen must not leave a hole in this screen's stack, and
    counting all of them against one corner would do exactly that.

    Order is preserved twice over. Within a group the cards keep the order
    they arrived in, so "oldest first" still means oldest first per
    monitor; and the returned list is in the caller's ORIGINAL index
    order, so it can be zipped straight back onto the card list.
    """
    anchors = list(anchors)
    groups: dict[tuple, list[int]] = {}
    for index, rect in enumerate(anchors):
        groups.setdefault(tuple(rect), []).append(index)
    places: list[tuple[int, int]] = [(0, 0)] * len(anchors)
    for rect, members in groups.items():
        for slot, index in enumerate(members):
            places[index] = stack_at(rect, size, corner, slot, len(members),
                                     margin, gap)
    return places


def bar_phase(elapsed: float, hovering: bool,
              announce_s: float = ANNOUNCE_S) -> str:
    """Which shape the clip bar has right now.

    Three states and one window: it says "Recording started" for a couple
    of seconds, shrinks to a pill that is a dot and a clock, and expands
    again whenever the pointer is on it. Pure, so the timings are testable
    without standing up a window — and so the painter and the resizer can
    never disagree about which shape they are drawing.
    """
    if hovering:
        return "hover"
    return "announce" if elapsed < announce_s else "timer"


def timer_width(label: str, buttons: int = 0) -> int:
    """How wide the pill has to be for `label` plus `buttons` controls.

    Measured against the real face rather than guessed: 7.4 px a character
    at 12.5 pt in the app's UI font, plus the dot, plus the padding. It
    grows for "1:02:09" and for the word "paused" instead of clipping
    them, because a clock that says "1:02:0" is worse than a wider pill.
    """
    width = 40 + int(7.4 * len(label)) + 14
    if buttons:
        width += buttons * (BAR_BTN + 6) + 6
    return max(88, width)


def stamp(when: float | None = None) -> str:
    """'2026-08-25 22-41-03' — sortable, and legal in a Windows filename.

    Hyphens where a clock would put colons. Sorting the folder by name is
    then the same as sorting it by time, which is the only ordering anyone
    ever wants out of a screenshots folder.
    """
    return time.strftime("%Y-%m-%d %H-%M-%S",
                         time.localtime(time.time() if when is None else when))


def capture_name(kind: str, when: float | None = None,
                 taken: set[str] | None = None) -> str:
    """'shot 2026-08-25 22-41-03.png', made unique against `taken`.

    Two captures inside one second are rare and not impossible — the key
    repeats — and silently overwriting the first one would be the worst
    possible answer. The second gets ' (2)'.

    The KIND is the first word of the filename, so one folder sorted by
    name groups the screen shots, the camera photos and the clips without
    needing three folders to look in.
    """
    suffix = {"shot": ".png", "photo": ".png", "clip": ".mp4"}[kind]
    base = f"{kind} {stamp(when)}"
    name = base + suffix
    if taken is None:
        return name
    n = 2
    while name in taken:
        name = f"{base} ({n}){suffix}"
        n += 1
    return name


def elapsed_readout(seconds: float) -> str:
    """'0:07' / '4:31' / '1:02:09' — a clock, not a float.

    Hours only appear once there are any: a recorder that says 0:00:07 is
    a recorder that expects to be running for hours, and this one mostly
    is not.
    """
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def size_readout(byte_count: int) -> str:
    """'812 KB' / '3.1 MB'. One decimal past a megabyte, none below."""
    if byte_count < 1024:
        return f"{int(byte_count)} B"
    kb = byte_count / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    return f"{kb / 1024:.1f} MB"


def crf_for(quality: str) -> int:
    """The one number that decides a screen recording's size.

    Screen content is mostly flat colour and sharp edges, which h264 likes:
    the numbers below are several steps softer than the same names would
    mean for camera video, and still look lossless on text at 1x.
    """
    return {"small": 30, "balanced": 26, "sharp": 20}[quality]


def plan_bar(anchor: tuple[int, int, int, int], bar: tuple[int, int],
             screen: tuple[int, int, int, int],
             gap: int = BAR_GAP) -> tuple[int, int]:
    """Where a toolbar goes relative to what it belongs to.

    Under the selection if it fits, over it if not, inside it as the last
    resort — a 1440-tall selection has no outside. Horizontally it is
    centred on the selection and then pushed back inside the monitor, in
    that order, because a bar that hangs off the screen loses buttons and
    a bar that is not centred merely looks untidy.
    """
    left, top, right, bottom = anchor
    bw, bh = bar
    sl, st, sr, sb = screen
    x = (left + right) // 2 - bw // 2
    x = max(sl + 8, min(x, sr - bw - 8))
    if bottom + gap + bh <= sb - 8:
        return (x, bottom + gap)
    if top - gap - bh >= st + 8:
        return (x, top - gap - bh)
    return (x, max(st + 8, min(bottom - bh - 8, sb - bh - 8)))


def undo_step(history: list) -> tuple[object | None, list]:
    """(the state to go back to, the history without it).

    History holds WHOLE STATES rather than inverse operations, because a
    crop is not a mark: undoing one has to put the rectangle back as well
    as the ink, and an "un-crop" that did not also restore the marks the
    crop cut off would be a different picture from the one that was there.
    A state is a rectangle, a polygon and a short list of point lists —
    small enough that copying it every stroke is free, and simple enough
    that undo cannot be subtly wrong.
    """
    if not history:
        return None, history
    return history[-1], history[:-1]


def should_stop(started: float, now: float, max_seconds: float) -> bool:
    """True when a recording has run past its cap. 0 = no cap."""
    return bool(max_seconds) and (now - started) >= max_seconds


# ------------------------------------------------- pure helpers, the lens
# Same rule as the ones above: numbers in, numbers out, a test for each.
# There is no webcam on a test runner and the shape of this feature has to
# be checkable anyway, so everything that can be decided without a device
# is decided here and the class below only drives the device.

def parse_size(text: str,
               fallback: tuple[int, int] = (1280, 720)) -> tuple[int, int]:
    """'1280x720' -> (1280, 720). Anything else -> `fallback`.

    A size that does not parse must not be the reason a key does nothing.
    config.check() has already refused the value out loud at load time;
    by the time we are here the only useful answer is a camera that opens.
    """
    try:
        left, _, right = str(text).lower().partition("x")
        width, height = int(left.strip()), int(right.strip())
    except (AttributeError, ValueError):
        return fallback
    if not (32 <= width <= 7680 and 32 <= height <= 4320):
        return fallback
    return width, height


# Every one of these installs a DirectShow video device that is not a
# camera. They are skipped when nothing was asked for by name — see below.
VIRTUAL_CAMERAS = ("virtual", "obs", "droidcam", "manycam", "splitcam",
                   "xsplit", "nvidia broadcast", "snap camera", "camo")


def pick_camera(names, wanted: str = "") -> str | None:
    """Which video device to open, out of what DirectShow listed.

    `wanted` matches as a case-insensitive SUBSTRING and not exactly.
    Webcam friendly names carry the vendor's own capitalisation and a lump
    of model number — "HD Webcam eMeet C960" — and asking the owner to
    retype one of those into config.toml without a typo is asking for the
    typo. "eMeet" is enough, and so is "c960".

    With nothing asked for, a VIRTUAL camera loses to a real one. OBS,
    Teams, Zoom and NVIDIA Broadcast each install one; they sort ahead of
    the real device as often as not (on this machine OBS is second of
    two), and a photo key that opens a black frame from a virtual camera
    nobody is streaming into is a photo key that looks broken.

    A name that was asked for and is not there returns None rather than
    quietly opening a different camera — the caller then falls back on
    purpose and SAYS which one it took. A photograph of the wrong room is
    not a smaller failure than no photograph.
    """
    names = [n for n in names if n]
    if not names:
        return None
    if wanted:
        needle = wanted.strip().lower()
        for name in names:
            if needle in name.lower():
                return name
        return None
    for name in names:
        if not any(mark in name.lower() for mark in VIRTUAL_CAMERAS):
            return name
    return names[0]


def preview_fit(size: tuple[int, int], work_area: tuple[int, int, int, int],
                strip: int = CAM_STRIP_H, pad: int = CAM_PAD,
                margin: int = 120) -> tuple[int, int]:
    """How big the live picture is shown — 1:1 whenever it fits.

    WHAT YOU SEE IS WHAT YOU GET is the rule this function exists to keep.
    The photo this window writes is the picture that was on the screen
    when the shutter fired, pixel for pixel: ONE image is the preview, the
    clipboard, the file and what the editor opens on, so none of them can
    disagree about what was taken. It is the argument render_shot makes
    for the screenshot key, applied to a lens.

    The price is that a camera larger than the monitor is photographed at
    what the monitor could show. Measured here: a 1280x720 camera is 1:1
    on this 2560x1440 monitor with room to spare. A 1080p camera on a
    1366x768 laptop is not, and comes out at the largest whole picture
    that fits. Lower `[camera] size` if you would rather have the pixels
    than the preview — the two cannot both be had without letting the file
    and the screen drift apart, which is the bug this avoids.
    """
    width, height = size
    left, top, right, bottom = work_area
    room_w = max(160, (right - left) - margin - pad * 2)
    room_h = max(120, (bottom - top) - margin - strip - pad)
    scale = min(1.0, room_w / max(1, width), room_h / max(1, height))
    return (max(2, int(width * scale) // 2 * 2),
            max(2, int(height * scale) // 2 * 2))


def next_in(values, current):
    """The value after `current`, wrapping. Anything unknown starts over."""
    values = tuple(values)
    if not values:
        return current
    try:
        return values[(values.index(current) + 1) % len(values)]
    except ValueError:
        return values[0]


def countdown_left(started: float, now: float, seconds: int) -> int:
    """What the self-timer should read: 3, 2, 1, then 0 meaning fire.

    Ceiling and not floor, so the number on screen is the number of
    seconds LEFT. A timer that floors shows "0" for a whole second before
    anything happens, and a timer that shows 0 for a whole second is a
    timer everybody presses again.
    """
    if seconds <= 0:
        return 0
    return max(0, int(math.ceil(seconds - (now - started))))


def camera_bar(width: int, switchable: bool = False) -> dict:
    """name -> (x0, y0, x1, y1) inside the control strip, in strip pixels.

    The same shape and the same reason as bar_layout: the painter and the
    hit test read ONE set of numbers, so a button cannot end up drawn a
    few pixels from where it can be clicked — invisible in a screenshot
    and maddening under the hand.

    The shutter is centred on the CARD rather than in the space left
    between the chips. A shutter is the one control on a camera that the
    hand finds without looking, and it finds it in the middle.
    """
    spots: dict[str, tuple[int, int, int, int]] = {}
    y = (CAM_STRIP_H - CAM_CHIP) // 2
    x = CAM_PAD
    for name in ("mirror", "timer"):
        spots[name] = (x, y, x + CAM_CHIP, y + CAM_CHIP)
        x += CAM_CHIP + GAP
    right = width - CAM_PAD
    for name in ("close", "switch") if switchable else ("close",):
        spots[name] = (right - CAM_CHIP, y, right, y + CAM_CHIP)
        right -= CAM_CHIP + GAP
    # Centred, then pushed off the chips if a narrow card leaves it
    # nowhere to be centred. Overlapping controls are not a cosmetic
    # problem: one press would mean two things, and the hit test would
    # decide which by dictionary order.
    sx = width // 2 - SHUTTER // 2
    sx = max(x + GAP, min(sx, right + CAM_CHIP - SHUTTER - GAP))
    sy = (CAM_STRIP_H - SHUTTER) // 2
    spots["shutter"] = (sx, sy, sx + SHUTTER, sy + SHUTTER)
    return spots



# ----------------------------------------------------------- win32 plumbing

# PRIVATE library handles, and this is not a style preference — it is a
# bug that cost an afternoon.
#
# `_user32` is a PROCESS-GLOBAL cached object, and every
# module in this app reaches for the same one. Setting `.restype` or
# `.argtypes` on a function taken from it changes that function FOR
# EVERYBODY. The first version of this file declared
# `_user32.GetDC.restype = c_void_p` (correct, and necessary
# here), and the next call into visual_qa.text_pil died with
# "OverflowError: int too long to convert" on a line that had worked for
# months: GetDC now handed back a full 64-bit pointer where that module
# still expected the truncated int ctypes gives an undeclared call.
#
# ctypes.WinDLL(name) builds a NEW wrapper with its own function cache, so
# the declarations below reach exactly this module. Nothing in capture.py
# may use ctypes.windll.* — there is a test that greps for it.
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0
DI_NORMAL = 0x0003
WDA_EXCLUDEFROMCAPTURE = 0x11
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
CURSOR_SHOWING = 0x00000001


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("flags", w.DWORD),
                ("hCursor", ctypes.c_void_p), ("ptScreenPos", w.POINT)]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    w.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.RECT),
    ctypes.c_ssize_t)


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", w.BOOL), ("xHotspot", w.DWORD),
                ("yHotspot", w.DWORD), ("hbmMask", ctypes.c_void_p),
                ("hbmColor", ctypes.c_void_p)]


def _declare() -> None:
    """Give every handle-carrying GDI/USER call its real signature.

    THE FIRST RECORDER DIED HERE. ctypes types an undeclared argument as
    c_int, and an HBITMAP on 64-bit Windows does not fit in one: the
    cursor draw captured frames correctly for a whole run and then raised
    "argument 1: OverflowError: int too long to convert" on
    DeleteObject(ii.hbmColor). Silent truncation is the worse cousin of
    the same bug — a DC handle that fits but is not the one you meant.
    Declared once at import, so no call site has to remember.
    """
    gdi32, user32 = _gdi32, _user32
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       w.UINT, ctypes.c_void_p,
                                       ctypes.c_void_p, w.DWORD]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                             ctypes.c_int, ctypes.c_int, w.DWORD]
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                  w.UINT, ctypes.c_void_p, w.UINT]
    user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, w.DWORD]
    user32.SetWindowDisplayAffinity.restype = w.BOOL
    # HMONITOR is a handle like any other. It is usually small enough that
    # an undeclared c_int gets away with it, which is exactly what makes
    # this the kind of bug that appears on somebody else's machine.
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           _MONITORENUMPROC, ctypes.c_ssize_t]


_declare()


def hide_from_capture(root) -> bool:
    """Make a Tk window invisible to every screen capture on this machine.

    WDA_EXCLUDEFROMCAPTURE, measured 2026-08-25: a saturated magenta
    borderless window that BitBlt returned 60000/60000 pixels of came back
    0/60000 with the flag set — with SRCCOPY, with SRCCOPY|CAPTUREBLT, and
    through PIL's ImageGrab. The desktop behind it is what lands in the
    frame, not a hole.

    This is what lets the clip bar sit ON the recorded region instead of
    beside it, which matters exactly when the region is the whole screen
    and there is no beside.
    """
    try:
        user32 = _user32
        hwnd = int(root.winfo_id())
        target = user32.GetParent(hwnd) or hwnd
        return bool(user32.SetWindowDisplayAffinity(
            ctypes.c_void_p(target), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        log.debug("could not exclude a window from capture", exc_info=True)
        return False


def no_activate(root) -> bool:
    """Let a window appear without taking the keyboard away from anything.

    A notification that steals focus is not a notification, it is an
    interruption with a countdown on it — and the whole point of the
    corner card is that the common case stops being interrupted. Measured
    before this existed: the card came up as `TkTopLevel` in the
    foreground, so a capture taken mid-sentence ate the next keystroke.

    `WS_EX_NOACTIVATE` is the flag for it. The window still receives the
    mouse — clicking the card works, it just does not focus it — which is
    exactly the bargain a toast wants. It has to be set BEFORE the window
    is first shown, so the caller builds it withdrawn and deiconifies
    after.
    """
    GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
    try:
        hwnd = int(root.winfo_id())
        target = _user32.GetParent(hwnd) or hwnd
        _user32.GetWindowLongW.restype = ctypes.c_long
        _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _user32.SetWindowLongW.restype = ctypes.c_long
        _user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                           ctypes.c_long]
        style = _user32.GetWindowLongW(ctypes.c_void_p(target), GWL_EXSTYLE)
        _user32.SetWindowLongW(ctypes.c_void_p(target), GWL_EXSTYLE,
                               style | WS_EX_NOACTIVATE)
        return True
    except Exception:
        log.debug("could not make the window non-activating", exc_info=True)
        return False


def esc_held() -> bool:
    """Is Escape being HELD DOWN right now, as opposed to just pressed?

    Every overlay in this app reads Escape with GetAsyncKeyState rather
    than receiving it, because a borderless topmost window does not get
    the keyboard for free. That works, and it has one failure mode that
    is invisible from the outside: if Escape is stuck down — an
    automation tool that injected a key-down without its key-up, a remote
    desktop session that dropped one, a wedged keyboard — then every
    overlay opens and closes again within one tick. The crosshair appears
    for an instant and vanishes, nothing is logged, and the app looks
    broken while dictation carries on working, because dictation is the
    one feature that never asks about Escape.

    That happened here on 2026-08-26 and cost real time to find. So the
    overlays now seed their Escape latch from this: a key that was
    ALREADY down when the window opened cannot close it. Release it and
    press it again and it cancels, exactly as before.
    """
    return bool(_user32.GetAsyncKeyState(0x1B) & 0x8000)


def give_focus_back(previous) -> None:
    """Hand the keyboard back to whatever had it before this window.

    TK TAKES THE FOREGROUND THE MOMENT IT REALISES A WINDOW, and
    WS_EX_NOACTIVATE does not stop it. Measured step by step on this
    machine, 2026-08-26: with the window `withdraw()`n, overrideredirect,
    topmost AND already carrying the no-activate flag, the foreground was
    still Chrome before `update_idletasks()` and TkTopLevel immediately
    after it. The flag does its job later — a click on the card no longer
    activates it — but the first grab has to be undone rather than
    prevented.

    Giving it back works because a process that currently OWNS the
    foreground is allowed to set it, and at that instant this one does.
    Painting afterwards does not take it again (measured over eight
    repaints).
    """
    if not previous:
        return
    try:
        _user32.SetForegroundWindow(ctypes.c_void_p(previous))
    except Exception:
        log.debug("could not hand the foreground back", exc_info=True)


def click_through(root) -> None:
    """WS_EX_TRANSPARENT: the mouse goes straight past this window.

    The frame drawn around a recording is decoration, not furniture. It
    covers the edge of whatever you are recording, and a border that ate
    the click on a tab you were trying to reach would make the recorder
    unusable for recording anything you have to operate.
    """
    try:
        user32 = _user32
        hwnd = int(root.winfo_id())
        target = user32.GetParent(hwnd) or hwnd
        setter = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        getter = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        getter.restype = ctypes.c_longlong
        getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
        setter.restype = ctypes.c_longlong
        setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
        style = getter(ctypes.c_void_p(target), GWL_EXSTYLE)
        setter(ctypes.c_void_p(target), GWL_EXSTYLE,
               style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception:
        log.debug("could not make a window click-through", exc_info=True)


def round_window(root, radius: int) -> None:
    """Round a borderless window's corners with SetWindowRgn.

    DWMWA_WINDOW_CORNER_PREFERENCE rounds the NON-CLIENT area and an
    overrideredirect window has none — AGENTS.md records that measurement
    and popup.py keeps this call as the answer. The region has to be
    re-cut after every resize.
    """
    try:
        gdi32, user32 = _gdi32, _user32
        root.update_idletasks()
        width, height = root.winfo_width(), root.winfo_height()
        gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1,
                                          radius * 2, radius * 2)
        hwnd = int(root.winfo_id())
        target = user32.GetParent(hwnd) or hwnd
        user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        w.BOOL]
        user32.SetWindowRgn(ctypes.c_void_p(target), ctypes.c_void_p(region),
                            True)
    except Exception:
        log.debug("could not round a window", exc_info=True)


class Grabber:
    """One region of the screen, grabbed over and over into one buffer.

    CreateDIBSection gives us a bitmap whose bits we can read directly, so
    a frame is one BitBlt and one memcpy — no CreateCompatibleBitmap, no
    GetDIBits, no allocation per frame. Measured against PIL's ImageGrab
    on the same rectangles: 10.1 ms vs 53.7 ms at 720p, 21.7 vs 56.7 at
    1440p. That is the difference between 30 fps and 18.

    The array `grab()` returns is a COPY, because the next grab overwrites
    the buffer this one is looking at and the encoder runs on another
    thread. `view()` hands out the live buffer for the one caller that
    consumes it before the next frame.
    """

    def __init__(self, box: tuple[int, int, int, int], cursor: bool = True):
        import numpy as np
        left, top, right, bottom = box
        self.box = (left, top, right - left, bottom - top)
        self.cursor = cursor
        width, height = self.box[2], self.box[3]
        if width < 2 or height < 2:
            raise CaptureError("that region is too small to record")
        gdi32, user32 = _gdi32, _user32
        self._screen_dc = user32.GetDC(None)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height          # negative = top-down
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        self._bitmap = gdi32.CreateDIBSection(
            self._screen_dc, ctypes.byref(info), DIB_RGB_COLORS,
            ctypes.byref(bits), None, 0)
        if not self._bitmap:
            raise CaptureError("Windows would not give us a capture buffer")
        gdi32.SelectObject(self._mem_dc, self._bitmap)
        self._view = np.ctypeslib.as_array(
            ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte)),
            shape=(height, width, 4))
        self._closed = False

    def _draw_cursor(self) -> None:
        """Paint the pointer into the frame we just took.

        BitBlt does not include it — the cursor is drawn by the compositor
        over everything, not into the screen bitmap — and a screen
        recording without a pointer is a recording where nobody can tell
        what is being pointed at. GetIconInfo hands back two bitmaps that
        are OURS to free; that pair is what made argtypes non-optional.
        """
        user32, gdi32 = _user32, _gdi32
        info = CURSORINFO()
        info.cbSize = ctypes.sizeof(CURSORINFO)
        if not user32.GetCursorInfo(ctypes.byref(info)):
            return
        if info.flags != CURSOR_SHOWING or not info.hCursor:
            return
        icon = ICONINFO()
        if not user32.GetIconInfo(ctypes.c_void_p(info.hCursor),
                                  ctypes.byref(icon)):
            return
        try:
            left, top = self.box[0], self.box[1]
            user32.DrawIconEx(
                self._mem_dc,
                info.ptScreenPos.x - left - icon.xHotspot,
                info.ptScreenPos.y - top - icon.yHotspot,
                ctypes.c_void_p(info.hCursor), 0, 0, 0, None, DI_NORMAL)
        finally:
            if icon.hbmMask:
                gdi32.DeleteObject(ctypes.c_void_p(icon.hbmMask))
            if icon.hbmColor:
                gdi32.DeleteObject(ctypes.c_void_p(icon.hbmColor))

    def view(self):
        """The live BGRA buffer, valid until the next grab()."""
        left, top, width, height = self.box
        _gdi32.BitBlt(self._mem_dc, 0, 0, width, height,
                                   self._screen_dc, left, top,
                                   SRCCOPY | CAPTUREBLT)
        if self.cursor:
            self._draw_cursor()
        return self._view

    def grab(self):
        """One frame as a private BGRA array (height, width, 4)."""
        return self.view().copy()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        gdi32, user32 = _gdi32, _user32
        self._view = None
        gdi32.DeleteObject(self._bitmap)
        gdi32.DeleteDC(self._mem_dc)
        user32.ReleaseDC(None, self._screen_dc)


# ------------------------------------------------------------- clipboard

def _image_formats(image) -> tuple[bytes, bytes]:
    """(CF_DIB payload, PNG payload) for one PIL image.

    CF_DIB is a BMP with its 14-byte file header cut off — that header is
    the only difference between the two, and every Windows app that says
    "bitmap" means the rest. It has no alpha, so a lasso is flattened onto
    WHITE here: Windows' own freeform snip does the same, and a document
    is the commonest place a cut-out gets pasted.

    The PNG goes on beside it under the registered "PNG" format, where
    everything modern looks first, and that one keeps the transparency.
    """
    from PIL import Image
    flat = image
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, (0, 0), rgba)
    dib = io.BytesIO()
    flat.convert("RGB").save(dib, "BMP")
    png = io.BytesIO()
    image.save(png, "PNG")
    return dib.getvalue()[14:], png.getvalue()


def copy_image(image) -> bool:
    """Put a picture on the clipboard in every format anything asks for.

    Measured 2026-08-25: 43 ms to encode a 640x360 shot into both formats
    (nearly all of it the BMP pass), 0.4 ms to write them. Setting CF_DIB
    makes Windows synthesise CF_BITMAP and CF_DIBV5 for free, so four
    formats are on the clipboard for the price of two.

    Never raises: a clipboard locked by another application is a normal
    Windows afternoon, and the capture is already safe on disk.

    QUEUED BEHIND THE REST OF THE PROCESS, through injector.board_held().
    A retry loop is not enough and never was: OpenClipboard does not
    serialise two threads of the same process — it hands the second one a
    success it cannot honour (popup.py has the measurement). This runs on
    `capture-shot`, which knows nothing about what main.py is doing, and
    the screenshot key can now be pressed in the middle of a dictation. So
    without the queue these two SetClipboardData calls can land inside the
    ~350 ms in which the target app is asynchronously reading a staged
    transcript, and the user gets the picture pasted into their document
    instead of their sentence — with the "..." marker already backspaced
    away and the transcript surviving only in transcripts.log.
    """
    try:
        import win32clipboard
        import win32con
        dib, png = _image_formats(image)
        cf_png = win32clipboard.RegisterClipboardFormat("PNG")
        injector = _injector()
        with _board(injector):
            opener = getattr(injector, "_open_clipboard", None)
            if opener is not None:
                opener()                # the retry loop injector.py already
            else:                       # paid for: another app may hold it
                win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_DIB, dib)
                win32clipboard.SetClipboardData(cf_png, png)
            finally:
                win32clipboard.CloseClipboard()
        return True
    except Exception as e:
        log.info("could not put the capture on the clipboard (%s) — it is "
                 "still saved to disk", e)
        return False


def copy_file(path: Path) -> bool:
    """Put a FILE on the clipboard, the way Explorer's Copy does.

    CF_HDROP, so the clip can be pasted into a chat window, an email, a
    folder — anywhere that accepts a dropped file. A video has no useful
    bitmap representation, and "the path as text" is not something you can
    paste into WhatsApp and have arrive as a video.

    The payload is a DROPFILES header followed by a double-NUL-terminated
    list of wide strings; pywin32 marshals the struct for us as long as we
    hand it bytes.
    """
    try:
        import struct
        import win32clipboard
        import win32con
        text = str(Path(path).resolve()) + "\0\0"
        # DROPFILES: pFiles offset, POINT pt, fNC, fWide
        header = struct.pack("Illii", 20, 0, 0, 0, 1)
        payload = header + text.encode("utf-16-le")
        injector = _injector()
        with _board(injector):
            # The queue AND the retry loop, neither of which this one had.
            # See copy_image for what each buys.
            opener = getattr(injector, "_open_clipboard", None)
            if opener is not None:
                opener()
            else:
                win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_HDROP, payload)
            finally:
                win32clipboard.CloseClipboard()
        return True
    except Exception as e:
        log.info("could not put %s on the clipboard (%s)", Path(path).name, e)
        return False


@contextlib.contextmanager
def _board(injector):
    """Take the process-wide clipboard queue, if there is one to take.

    A context manager rather than a plain call so that the "injector is
    not importable" case — which this module has always had to survive,
    being usable on its own — costs one bare yield and no branching at
    either call site.
    """
    held = getattr(injector, "board_held", None)
    if held is None:
        yield
        return
    with held():
        yield


def _injector():
    """injector.py if it is importable, else None. Imported late on
    purpose: this module is constructed at startup and injector pulls in
    pywin32."""
    try:
        import injector
        return injector
    except Exception:
        return None


# ----------------------------------------------------------------- the ink
# Pixels in, pixels out. No file path appears in any signature here, and a
# test asserts it — the same rule visual_qa's screenshot pipeline keeps.

def _shift(points, dx: int, dy: int) -> list:
    return [(x - dx, y - dy) for x, y in points]


def arrow_shape(start, end, width: int = PEN_W):
    """(where the shaft stops, the head polygon) for one arrow.

    FOUR POINTS, NOT THREE: the tip, the two barbs, and a NOTCH pulled
    back along the shaft between them. A plain triangle on a thin shaft
    reads as a wedge stuck on a line; the notch is what makes it read as
    an arrow at a glance, and it is the shape every drawing tool has
    settled on for that reason.

    THE SHAFT STOPS AT THE NOTCH, not at the tip. Drawn to the tip, a
    3 px stroke pokes out the far side of the point — which is what the
    little nub above the arrowhead was in the first screenshot of this
    editor, and it is visible at 1x once you know to look.

    The head is proportional to the STROKE (so it never looks like a
    scratch) and capped against the arrow's LENGTH (so a short arrow does
    not become a blob with a tail).
    """
    import math
    x0, y0 = start
    x1, y1 = end
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return end, []
    head = min(max(ARROW_HEAD_MIN, width * ARROW_HEAD), length * 0.38)
    angle = math.atan2(y1 - y0, x1 - x0)
    spread = math.radians(ARROW_SPREAD)
    back = head * ARROW_NOTCH
    notch = (x1 - back * math.cos(angle), y1 - back * math.sin(angle))
    return notch, [
        (x1, y1),
        (x1 - head * math.cos(angle - spread),
         y1 - head * math.sin(angle - spread)),
        notch,
        (x1 - head * math.cos(angle + spread),
         y1 - head * math.sin(angle + spread)),
    ]


def tk_arrowshape(width: int = PEN_W) -> tuple[int, int, int]:
    """The same head, in the three numbers Tk's canvas wants.

    Tk draws the live preview and Pillow draws the picture, and they are
    two different arrowheads unless somebody makes them agree. This is
    that somebody: (neck-to-tip, barb-to-tip, half-width), read off the
    geometry above so a change there moves both.
    """
    import math
    head = max(ARROW_HEAD_MIN, width * ARROW_HEAD)
    return (max(2, round(head * ARROW_NOTCH)), max(3, round(head)),
            max(2, round(head * math.sin(math.radians(ARROW_SPREAD)))))


def ink_scale(width: int, height: int) -> int:
    """How far to oversample one mark's own rectangle before shrinking it.

    PILLOW ANTIALIASES NOTHING. `ImageDraw.line` and `.polygon` write hard
    pixels, so every diagonal an arrow or a pen stroke makes comes out as
    a staircase — plainly visible at 1x and the reason the first version
    of this editor's ink looked hand-cut. The fix is the one `icon()` and
    `rr_layer` already use: draw it big and shrink it with LANCZOS.

    Big is not free, and a mark's rectangle can be the whole picture (one
    arrow corner to corner). So the factor is whatever fits the budget:
    4x for the marks people actually draw, dropping to 2x for the ones
    that span a 1440p screenshot. Measured on this machine, per mark:

        220x160 box       4x     1.9 ms
        1280x720 arrow    2x    24.0 ms
        2560x1440 arrow   1x     3.1 ms   (too big to oversample at all)

    and none of it is per-frame — `ShotWindow.picture()` caches on a
    revision counter, so this runs when the ink changes and not when the
    pointer moves.
    """
    area = max(1, width * height)
    for scale in (INK_SS, 3, 2):
        if area * scale * scale <= INK_SS_BUDGET:
            return scale
    return 1


def pixelate(image, box, block: int = PIXEL_BLOCK):
    """A mosaic over one rectangle of `image`. Returns a NEW image.

    Down to 1/block and back up with NEAREST, which is a mosaic rather
    than a blur on purpose: a Gaussian at any radius a person will accept
    can be sharpened back, and this is the tool people reach for when the
    thing under it is an address or a token. 12 px blocks were picked by
    reading the result: at 8 px a 12 pt password was still guessable.
    """
    from PIL import Image
    left, top, right, bottom = clamp_box(box, (0, 0, image.width, image.height))
    if right - left < 2 or bottom - top < 2:
        return image
    out = image.copy()
    patch = out.crop((left, top, right, bottom))
    small = patch.resize((max(1, patch.width // block),
                          max(1, patch.height // block)), Image.BILINEAR)
    out.paste(small.resize(patch.size, Image.NEAREST), (left, top))
    return out


# One rendered stamp per mark, because a mark never changes after it is
# committed — a crop only moves where it is PASTED. Without this, every
# repaint of a picture carrying eight marks would oversample all eight
# again, and the whole point of oversampling is that it is not cheap.
_INK_CACHE: dict = {}
_INK_CACHE_MAX = 64


def _ink_stamp(kind: str, points: tuple, colour: tuple):
    """(the mark as a small RGBA image, where its top-left belongs).

    Both in the marks' own coordinate space — virtual-screen pixels — so
    the caller subtracts the crop's origin and nothing here has to know
    what is being cropped to.
    """
    key = (kind, points, colour)
    stamp = _INK_CACHE.get(key)
    if stamp is not None:
        return stamp

    from PIL import Image, ImageDraw
    pad = _MARK_PAD.get(kind, PEN_W + 2)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    left, top = int(min(xs)) - pad, int(min(ys)) - pad
    width = int(max(xs)) + pad + 1 - left
    height = int(max(ys)) + pad + 1 - top
    scale = ink_scale(width, height)
    layer = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    at = [((x - left) * scale, (y - top) * scale) for x, y in points]
    solid = tuple(colour) + (255,)
    radius = PEN_W * scale / 2

    def cap(x, y) -> None:
        """Round ends, which ImageDraw has no keyword for. A flat cap on a
        3 px stroke is a visible chisel at either end of every squiggle."""
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=solid)

    if kind == "pen":
        draw.line(at, fill=solid, width=PEN_W * scale, joint="curve")
        cap(*at[0])
        cap(*at[-1])
    elif kind == "arrow":
        notch, head = arrow_shape(points[0], points[-1], PEN_W)
        draw.line([at[0], ((notch[0] - left) * scale,
                           (notch[1] - top) * scale)],
                  fill=solid, width=PEN_W * scale)
        cap(*at[0])
        if head:
            draw.polygon([((x - left) * scale, (y - top) * scale)
                          for x, y in head], fill=solid)
    elif kind == "box":
        x0, y0, x1, y1 = normalize_bbox(at[0][0], at[0][1],
                                        at[-1][0], at[-1][1])
        draw.rounded_rectangle((x0, y0, x1, y1), 4 * scale, outline=solid,
                               width=BOX_W * scale)
    elif kind == "highlight":
        draw.line(at, fill=tuple(colour) + (HIGHLIGHT_A,),
                  width=HIGHLIGHT_W * scale, joint="curve")
    else:
        return None

    if scale > 1:
        layer = layer.resize((width, height), Image.LANCZOS)
    if len(_INK_CACHE) >= _INK_CACHE_MAX:
        _INK_CACHE.clear()          # a whole generation at a time: the
    _INK_CACHE[key] = (layer, (left, top))    # entries are all the same
    return _INK_CACHE[key]                    # age and none is special


def _ink(out, kind: str, points, colour: tuple, origin: tuple[int, int]):
    """Composite one mark onto the picture, clipped to it.

    `alpha_composite` refuses a paste that hangs off the edge, and a mark
    hanging off the edge is the NORMAL case after a crop — so the stamp is
    trimmed to the overlap first rather than the picture being padded.
    """
    if len(points) < 2:
        return out
    stamp = _ink_stamp(kind, tuple(map(tuple, points)), tuple(colour))
    if stamp is None:
        return out
    layer, (mleft, mtop) = stamp
    x, y = mleft - origin[0], mtop - origin[1]
    cx0, cy0 = max(0, -x), max(0, -y)
    cx1 = min(layer.width, out.width - x)
    cy1 = min(layer.height, out.height - y)
    if cx1 <= cx0 or cy1 <= cy0:
        return out                   # cropped clean out of the picture
    if (cx0, cy0, cx1, cy1) != (0, 0, layer.width, layer.height):
        layer = layer.crop((cx0, cy0, cx1, cy1))
    out.alpha_composite(layer, (x + cx0, y + cy0))
    return out


def draw_marks(image, marks: list, origin: tuple[int, int]):
    """Replay every mark into a pristine picture. Returns a NEW image.

    NEVER by grabbing the screen back to read our own ink — that races the
    topmost window and returns black, which visual_qa.py records paying
    for. The canvas items under the pointer are a preview; THIS is the
    picture, and it is rebuilt from points every time.

    `origin` is where `image` sits on the virtual screen, because marks
    are stored in virtual-screen coordinates: a crop then changes the
    origin and nothing else, and undoing the crop puts every mark back
    exactly where it was drawn.

    Everything with an edge goes through `_ink`, which oversamples and
    caches. The blur does not: a mosaic has no edges to soften, and
    softening the ones between its blocks would be undoing the point of
    it.
    """
    out = image.convert("RGBA")
    for mark in marks:
        kind = mark["kind"]
        colour = tuple(mark.get("colour", INKS[0][1]))
        points = mark.get("points", ())
        if kind == "blur":
            shifted = _shift(points, *origin)
            if len(shifted) >= 2:
                out = pixelate(out, (shifted[0][0], shifted[0][1],
                                     shifted[-1][0], shifted[-1][1]))
            continue
        out = _ink(out, kind, points, colour, origin)
    return out


def cut_to_shape(image, shape: list, origin: tuple[int, int]):
    """Keep what is inside the lasso, make the rest TRANSPARENT.

    Deliberately different from visual_qa, which fills the outside BLACK:
    there the crop is going to a model that would happily describe a
    dimmed neighbour, so the neighbour has to be gone. Here the crop is
    going into a document, and transparency is what lets it land on
    whatever colour that document already is. The clipboard's CF_DIB copy
    is flattened onto white for the applications that cannot read alpha.
    """
    from PIL import Image, ImageDraw
    dx, dy = origin
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon(_shift(shape, dx, dy), fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def render_shot(base, box: tuple[int, int, int, int], marks: list,
                shape: list | None = None, screen_origin=(0, 0)):
    """The picture as it stands: crop, lasso, ink — in that order.

    One function, called by the editor to paint the screen AND by the
    saver to write the file, so what you see really is what is written.
    The order matters: cropping after the ink would cut marks in half, and
    lassoing after the ink would erase the parts of an arrow that left the
    shape. The lasso argument is `shape`, never `path`: this module writes
    FILES, and one word meaning both a polygon and a place on disk is one
    word too few.
    """
    ox, oy = screen_origin
    left, top, right, bottom = box
    crop = base.crop((left - ox, top - oy, right - ox, bottom - oy))
    if shape:
        crop = cut_to_shape(crop, shape, (left, top))
    if marks:
        crop = draw_marks(crop, marks, (left, top))
    return crop


# ------------------------------------------------------------- the folder

def capture_dir(folder: str) -> Path:
    """Where captures go, made if it is not there yet.

    A relative name is relative to the APP, not to whatever directory the
    process happened to start in — the app is launched from a .vbs, from a
    shortcut and from a scheduled task, and all three have different ideas
    about the working directory.
    """
    path = Path(folder).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# THE GLOB AND THE WRITE HAVE TO BE ONE STEP. capture_name picks a name by
# looking at what is already in the folder, so two saves that read the
# folder before either has written it choose the SAME name and the second
# silently overwrites the first. That was impossible while a capture flow
# was strictly sequential; it stopped being impossible the moment the cards
# stacked, because two cards can both have a Save button under a hand in
# the same second. A Lock is not a Tk object, so the "nothing module-level
# holds a Tk object" rule has nothing to say about it.
_SAVE_LOCK = threading.Lock()


def save_image(image, folder: str, when: float | None = None,
               kind: str = "shot") -> Path:
    """Write a picture and return where it went.

    `kind` is "shot" off the screenshot key and "photo" off the camera
    key. Same folder, same PNG, different first word — see capture_name.
    """
    with _SAVE_LOCK:
        directory = capture_dir(folder)
        taken = {p.name for p in directory.glob(f"{kind} *.png")}
        path = directory / capture_name(kind, when, taken)
        image.save(path, "PNG")
    return path


def open_folder(path: Path) -> None:
    """Show a file in Explorer, selected.

    CREATE_NO_WINDOW because this app runs under pythonw and every
    subprocess without it allocates a console that freezes the UI thread
    for hundreds of milliseconds — the trap AGENTS.md lists and the
    dashboard has already been bitten by.
    """
    import subprocess
    try:
        subprocess.Popen(["explorer", "/select,", str(Path(path).resolve())],
                         creationflags=0x08000000)
    except Exception:
        log.debug("could not open the captures folder", exc_info=True)


# --------------------------------------------------------------- recording

class Clip:
    """One mp4 being written: a video stream, optionally an audio one.

    The container is opened when the first frame arrives rather than at
    construction, so a recording that fails to start leaves no zero-byte
    file behind, and so the stream's timebase is anchored to a real
    first frame.
    """

    def __init__(self, path: Path, size: tuple[int, int], fps: int,
                 crf: int, audio_rate: int = 0):
        self.path = Path(path)
        self.size = size
        self.fps = fps
        self.crf = crf
        self.audio_rate = audio_rate
        self._container = None
        self._video = None
        self._audio = None
        self._resampler = None
        self._audio_pts = 0
        self.frames = 0

    def _open(self) -> None:
        import fractions
        import av
        self._container = av.open(str(self.path), mode="w")
        width, height = self.size
        stream = self._container.add_stream("libx264", rate=self.fps)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        # veryfast rather than ultrafast: measured on this machine the
        # step costs 0.6 ms a frame at 720p and halves the file (81 KB ->
        # 40 KB over 90 frames). zerolatency because the encoder must not
        # hold frames back — a recorder that buffers is a recorder that
        # loses the last second when you stop it.
        stream.options = {"preset": "veryfast", "tune": "zerolatency",
                          "crf": str(self.crf)}
        # WALL-CLOCK STAMPS, not frame numbers. A grab that could only
        # manage 24 fps must not play back 20% fast; every frame carries
        # the millisecond it was taken at instead.
        stream.codec_context.time_base = fractions.Fraction(1, CLOCK_HZ)
        self._video = stream
        if self.audio_rate:
            import av.audio.resampler
            audio = self._container.add_stream("aac", rate=self.audio_rate)
            audio.layout = "mono"
            self._audio = audio
            self._resampler = av.audio.resampler.AudioResampler(
                format="fltp", layout="mono", rate=self.audio_rate)

    def add_frame(self, bgra, at_ms: int) -> None:
        import fractions
        import av
        if self._container is None:
            self._open()
        frame = av.VideoFrame.from_ndarray(bgra, format="bgra")
        frame.pts = int(at_ms)
        frame.time_base = fractions.Fraction(1, CLOCK_HZ)
        for packet in self._video.encode(frame):
            self._container.mux(packet)
        self.frames += 1

    def add_audio(self, samples) -> None:
        """int16 mono samples. Their OWN clock, and that is the point.

        Video stamps come from the wall clock because frames arrive when
        they arrive; audio is a continuous stream at a fixed rate, so its
        sample count IS the time. Anchoring each to what it actually knows
        is what keeps a ten-minute clip in sync — a shared wall clock
        would put a jitter of tens of milliseconds into the audio, which
        is audible, to save a jitter in the video, which is not.
        """
        import av
        if self._container is None or self._audio is None:
            return
        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = self.audio_rate
        frame.pts = self._audio_pts
        self._audio_pts += samples.shape[0]
        for resampled in self._resampler.resample(frame):
            for packet in self._audio.encode(resampled):
                self._container.mux(packet)

    def close(self) -> Path | None:
        """Flush both encoders and close. Returns the path, or None when
        nothing was ever written."""
        if self._container is None:
            return None
        try:
            for packet in self._video.encode():
                self._container.mux(packet)
            if self._audio is not None:
                for packet in self._audio.encode():
                    self._container.mux(packet)
        except Exception:
            log.debug("flushing the clip's encoder failed", exc_info=True)
        finally:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
        return self.path


class ScreenRecorder:
    """Region -> mp4, on two threads with a bounded queue between them.

    The capture thread paces itself against a wall clock and never waits
    on the encoder; the encoder drains as fast as it can. The queue is
    small (8 frames, ~28 MB at 1080p) because a big one only buys the
    right to fall further behind before anybody notices — measured 0
    dropped frames at 720p and 1080p, and 0 at 1440p once the pace fell
    to the 28 fps the grab could actually sustain.

    Pausing stops queueing frames and holds the clock still, so a pause is
    a cut rather than a freeze-frame.
    """

    def __init__(self, box: tuple[int, int, int, int], path: Path, *,
                 fps: int = 30, quality: str = "balanced",
                 cursor: bool = True, audio: bool = False, audio_device=None,
                 audio_rate: int = 48000, max_seconds: float = 0.0):
        self.box = even_box(box)
        self.path = Path(path)
        self.fps = max(5, min(60, int(fps)))
        self.quality = quality
        self.cursor = cursor
        # A separate flag from the device, because None is a legal DEVICE
        # (sounddevice reads it as "the system default input") and would
        # otherwise be indistinguishable from "no sound wanted".
        self.audio_device = audio_device
        self.audio_rate = audio_rate if audio else 0
        self.max_seconds = max_seconds
        self.started_at = 0.0
        self.error: str | None = None
        self.audio_on = False
        self.discard = False
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._muted = threading.Event()
        self._paused_ms = 0.0
        self._pause_started = 0.0
        self._queue: queue.Queue = queue.Queue(maxsize=8)
        self._threads: list[threading.Thread] = []
        self._clip: Clip | None = None
        self.dropped = 0

    # -- the numbers the bar shows --

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        now = time.monotonic()
        held = self._paused_ms / 1000.0
        if self._paused.is_set():
            held += now - self._pause_started
        return max(0.0, now - self.started_at - held)

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_rate)

    @property
    def frames_written(self) -> int:
        return self._clip.frames if self._clip is not None else 0

    @property
    def size_on_disk(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    # -- lifecycle --

    def start(self) -> None:
        left, top, right, bottom = self.box
        self._clip = Clip(self.path, (right - left, bottom - top), self.fps,
                          crf_for(self.quality), self.audio_rate)
        self.audio_on = bool(self.audio_rate)
        self.started_at = time.monotonic()
        self._threads = [
            threading.Thread(target=self._capture, daemon=True,
                             name="clip-capture"),
            threading.Thread(target=self._encode, daemon=True,
                             name="clip-encode"),
        ]
        if self.audio_rate:
            self._threads.append(threading.Thread(
                target=self._listen, daemon=True, name="clip-audio"))
        for thread in self._threads:
            thread.start()

    def toggle_pause(self) -> bool:
        if self._paused.is_set():
            self._paused_ms += (time.monotonic() - self._pause_started) * 1000
            self._paused.clear()
        else:
            self._pause_started = time.monotonic()
            self._paused.set()
        return self._paused.is_set()

    def toggle_mute(self) -> bool:
        """Silence the microphone without removing the track.

        An mp4 declares its streams when the container opens, which is at
        the FIRST FRAME — adding a track later means remuxing the file. So
        the button on the bar cannot add sound to a silent recording, and
        pretending otherwise would be a lie in the shape of a switch. What
        it can do is feed SILENCE instead of the microphone, which keeps
        the sample clock advancing and therefore keeps the picture in sync
        with whatever comes after the muted stretch.
        """
        if self._muted.is_set():
            self._muted.clear()
        else:
            self._muted.set()
        return self._muted.is_set()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def finish(self, timeout: float = 8.0) -> Path | None:
        """Wait for both threads and close the file. Returns the path, or
        None if nothing was recorded."""
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        written = self._clip.close() if self._clip is not None else None
        if written is not None and self._clip.frames == 0:
            try:
                written.unlink()
            except OSError:
                pass
            return None
        return written

    # -- threads --

    def _capture(self) -> None:
        grabber = None
        try:
            grabber = Grabber(self.box, cursor=self.cursor)
            period = 1.0 / self.fps
            start = time.monotonic()
            due = start
            while not self._stop.is_set():
                if should_stop(start, time.monotonic(), self.max_seconds):
                    log.info("the recording hit its %.0f minute cap and "
                             "stopped itself", self.max_seconds / 60)
                    self._stop.set()
                    break
                if self._paused.is_set():
                    time.sleep(0.05)
                    due = time.monotonic()
                    continue
                frame = grabber.grab()
                stamp_ms = int(self.elapsed * 1000)
                try:
                    self._queue.put_nowait((frame, stamp_ms))
                except queue.Full:
                    # The encoder is behind. Dropping the NEWEST frame is
                    # wrong (it is the one the user is looking at) and
                    # blocking is worse (the pace collapses and never
                    # recovers), so the frame is dropped and counted — the
                    # count is what tells us whether a preset was too slow.
                    self.dropped += 1
                due += period
                rest = due - time.monotonic()
                if rest > 0:
                    time.sleep(rest)
                else:
                    due = time.monotonic()
        except Exception as e:
            self.error = str(e)
            log.exception("the screen recorder's capture thread stopped")
            self._stop.set()
        finally:
            if grabber is not None:
                grabber.close()
            self._queue.put(None)

    def _encode(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                frame, stamp_ms = item
                self._clip.add_frame(frame, stamp_ms)
        except Exception as e:
            self.error = str(e)
            log.exception("the screen recorder's encoder stopped")
            self._stop.set()

    def _listen(self) -> None:
        """The microphone, when the user asked for it.

        A SECOND stream on the same device as dictation's, opened only for
        the length of the clip. Verified on this machine 2026-08-25: two
        simultaneous 16 kHz shared-mode InputStreams on the Arctis 7 both
        deliver audio, so a recording does not cost you the hotkey. If the
        driver ever refuses, the clip loses its sound and keeps its
        picture — never the other way round.
        """
        try:
            import numpy as np
            import sounddevice as sd

            from recorder import wasapi_auto_convert
            block = self.audio_rate // 10
            # The rate is NOT negotiable here the way it is for dictation:
            # the container declared its audio stream at this rate when the
            # first frame went in (Clip.open), so audio arriving at another
            # rate would drift against the picture. When the driver refuses
            # it, ask WASAPI to convert instead of giving up — the same
            # rung recorder.py grew on 2026-09-05, against the same class
            # of driver (the Arctis 7 Chat refuses shared-mode rates it
            # does not natively hold). Without it, a refused rate landed in
            # the broad except below and shipped a MUTE clip.
            rungs = [{}]
            wasapi = wasapi_auto_convert()
            if wasapi is not None:
                rungs.append({"extra_settings": wasapi})
            stream = None
            refused: Exception | None = None
            for rung in rungs:
                try:
                    stream = sd.InputStream(
                        samplerate=self.audio_rate, channels=1,
                        dtype="int16", device=self.audio_device,
                        blocksize=block, **rung)
                    break
                except sd.PortAudioError as e:
                    refused = e
            if stream is None:
                raise refused
            with stream:
                self.audio_on = True
                while not self._stop.is_set():
                    data, _overflow = stream.read(block)
                    if self._paused.is_set():
                        continue
                    if self._muted.is_set():
                        # SILENCE, not nothing. Skipping the write would
                        # stop the sample clock and slide everything after
                        # the mute earlier than the picture it belongs to.
                        self._clip.add_audio(np.zeros(data.shape[0],
                                                      dtype="int16"))
                        continue
                    self._clip.add_audio(np.ascontiguousarray(data[:, 0]))
        except Exception as e:
            self.audio_on = False
            # WARNING, not INFO. A silent recording is not a detail: the
            # clip looks finished, plays, and is missing half of what was
            # in the room, and the person who made it finds out later.
            log.warning("the recording has no sound (%s) — the picture is "
                        "unaffected, but this clip is mute", e)


# ----------------------------------------------------------- the webcam
# The other camera on this machine: the one with a lens. It arrives
# through the SAME PyAV that encodes the recordings — faster-whisper's own
# dependency, carrying its own FFmpeg with the dshow demuxer built in — so
# the photo key adds no package, no ffmpeg.exe and no OpenCV.


def _dshow_report(options: dict) -> str:
    """Run one dshow probe for its LOG and give back everything it said.

    Listing devices in FFmpeg is not a query, it is an error: you open the
    demuxer with `list_devices=true`, it prints the list and refuses to
    open, and the refusal is the normal outcome. So the exception here is
    swallowed on purpose — an immediate-exit from this call means it
    worked.

    TWO THINGS ABOUT THAT LOG, both paid for on 2026-08-26:

    - Read it through PYTHON LOGGING, not stderr. PyAV's default callback
      hands ffmpeg's lines to `logging.getLogger("libav.*")`, which is the
      only route that survives pythonw:
      `av.logging.restore_default_callback()` sends them to the C
      runtime's stderr instead, and redirecting fd 2 around the call
      captured NOTHING — measured, zero lines, twice. A windowless app has
      nowhere for stderr to go.
    - What arrives are FRAGMENTS, not lines. One device shows up as four
      records — the quoted name, "(video", ")", and the newline — and off
      the main thread the newline is dropped as well, so the whole listing
      comes back as one run-on string. Both are joined and read with a
      regex rather than split on lines, because the line breaks are not
      dependably there.

    The `libav` logger is muted for the length of the call. Without that
    every probe would put twenty fragments of DirectShow trivia into
    app.log, which is a log nobody would keep reading.
    """
    import av

    rows: list[str] = []

    class _Sink(logging.Handler):
        def emit(self, record) -> None:
            rows.append(record.getMessage())

    logger = logging.getLogger("libav")
    sink = _Sink()
    before_level = av.logging.get_level()
    before_prop, before_own = logger.propagate, logger.level
    logger.addHandler(sink)
    logger.propagate = False
    # BOTH levels, and forgetting the second one is how this returned an
    # empty list the first time it ran: ffmpeg's lines arrive at INFO, and
    # an unset logger inherits root's WARNING, which drops every one of
    # them before any handler is consulted.
    logger.setLevel(logging.DEBUG)
    try:
        av.logging.set_level(av.logging.INFO)
        try:
            av.open("dummy", format="dshow", options=options)
        except Exception:
            pass                      # the listing ALWAYS ends in an error
    finally:
        av.logging.set_level(before_level)
        logger.setLevel(before_own)
        logger.propagate = before_prop
        logger.removeHandler(sink)
    return "".join(rows)


def read_video_devices(report: str) -> list[str]:
    """The camera names out of one dshow report. Pure, so it has a test.

    A video device is a quoted name followed by "(video)"; the same report
    carries the microphones ("(audio)") and an "Alternative name" line per
    device, which is also quoted and must not be mistaken for one.
    """
    import re
    return re.findall(r'"([^"]+)"\s*\(\s*video\s*\)', report)


def cameras() -> list[str]:
    """Every video device DirectShow will answer to, in its own order.

    FFmpeg has no "default camera" URL — dshow is opened as
    `video=<friendly name>` — so a key that opens the camera has to find
    out what the cameras are called first. Measured 147 ms on this
    machine, paid once when the window opens and again only if you ask to
    switch.
    """
    try:
        names = read_video_devices(_dshow_report({"list_devices": "true"}))
    except Exception:
        log.exception("could not ask DirectShow what cameras there are")
        return []
    log.debug("cameras: %s", ", ".join(names) or "none")
    return names


class Camera:
    """One webcam, open, holding the newest picture it has made.

    IT GETS ITS OWN THREAD, and not because decoding is expensive — 5.4 ms
    for a 720p MJPEG frame here — but because `demux()` BLOCKS until the
    device has something. Pumped from the Tk loop it would tie the
    window's repaint rate to the camera's exposure, and a webcam that
    drops to 12 fps in a dim room would take the whole window down with
    it. This way the window paints at its own tick and shows whatever the
    last frame was.

    ONE IMAGE PER FRAME, already at the size the window will show, and
    that image is both the preview and the photo. preview_fit explains why
    that identity is worth more than the pixels it costs.

    MEASURED HERE, 2026-08-26, on an eMeet C960 over USB:

        open -> first frame            654-829 ms over six opens
        decode + reformat to 800x450     5.4 ms
        decode + to_image at 1280x720    4.3 ms
        delivered                         25 fps (40.1 ms between frames,
                                          steady to a tenth of a ms)

    ASK FOR MJPEG. It is not a preference, it is the difference between a
    preview and a slideshow: this camera offers 1920x1080 at 30 fps as
    mjpeg and the SAME size at 5 fps as yuyv422, and dshow takes the raw
    one unless it is told otherwise. The fallback below drops the request
    rather than fail, because a 5 fps camera is still a camera and a black
    window is not.
    """

    def __init__(self, name: str, size: tuple[int, int] = (1280, 720),
                 fps: int = 30, preview: tuple[int, int] | None = None,
                 mirror: bool = False):
        self.name = name
        self.size = size
        self.fps = max(1, int(fps))
        self.preview_size = preview or size
        self.mirror = mirror           # read by the thread, set by the window
        self.error: str | None = None
        self.frames = 0
        self.raw_codec = ""
        self.opened_at = 0.0
        self.first_frame_ms = 0.0
        self._latest = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.opened_at = time.monotonic()
        self._thread = threading.Thread(target=self._pump, daemon=True,
                                        name="camera")
        self._thread.start()

    @property
    def live(self) -> bool:
        return self._latest is not None

    @property
    def latest(self):
        """The newest picture, or None while the camera is still waking."""
        with self._lock:
            return self._latest

    def still(self):
        """The photo: a private copy of exactly what the preview shows.

        A copy because the thread replaces `_latest` twenty-five times a
        second and the picture is about to be written to a file, put on
        the clipboard and drawn on.
        """
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def close(self, timeout: float = 2.0) -> None:
        """Stop the thread and let go of the device — the light goes out.

        Called the instant the shutter fires, not when the window closes.
        A camera left open through an editing session is a lens pointed at
        the room for no reason, and the little light beside it is the only
        thing the owner has to go on.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    # -- the thread --

    def _open(self):
        import av
        width, height = self.size
        options = {"video_size": f"{width}x{height}",
                   "framerate": str(self.fps),
                   "rtbufsize": "64M",
                   "vcodec": "mjpeg"}
        try:
            container = av.open(f"video={self.name}", format="dshow",
                                options=options)
            self.raw_codec = "mjpeg"
            return container
        except Exception as refused:
            # Not every camera has an MJPEG pin. Ask again for whatever it
            # does have rather than fail: raw YUV at 5 fps is a working
            # camera, and this is logged so a slow preview has a reason.
            log.info("%r would not give mjpeg at %dx%d (%s) - taking "
                     "whatever it offers", self.name, width, height, refused)
            options.pop("vcodec")
            container = av.open(f"video={self.name}", format="dshow",
                                options=options)
            self.raw_codec = "raw"
            return container

    def _pump(self) -> None:
        container = None
        try:
            container = self._open()
            stream = container.streams.video[0]
            for packet in container.demux(stream):
                if self._stop.is_set():
                    break
                for frame in packet.decode():
                    self._take(frame)
                    if self._stop.is_set():
                        break
        except Exception as e:
            self.error = str(e).strip() or e.__class__.__name__
            log.warning("the camera %r stopped: %s", self.name, self.error)
            log.debug("camera traceback", exc_info=True)
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    log.debug("closing the camera raised", exc_info=True)

    def _take(self, frame) -> None:
        """One decoded frame -> the picture the window will show.

        The mirror is applied HERE and nowhere else. It is the whole
        reason `_latest` can be handed to the painter and to the file
        without a second thought: whatever the window is showing is
        whatever gets written, mirrored or not, and there is no second
        code path to keep in step.
        """
        from PIL import Image
        width, height = self.preview_size
        image = frame.reformat(width=width, height=height,
                               format="rgb24").to_image()
        if self.mirror:
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
        with self._lock:
            self._latest = image
        if not self.frames:
            self.first_frame_ms = (time.monotonic() - self.opened_at) * 1000
            log.info("camera %r awake in %.0f ms - %dx%d %s, shown at %dx%d",
                     self.name, self.first_frame_ms, self.size[0],
                     self.size[1], self.raw_codec, width, height)
        self.frames += 1


# ------------------------------------------------------------------ icons

_SHARED_ICONS = ("pencil", "undo", "trash", "close", "copy", "send",
                 "keyboard", "mic", "pin", "speak")


def icon(kind: str, size: int = 20, colour=INK, width: int = 2):
    """One line icon. The shapes both windows use come from visual_qa.

    So the pencil on the ask card and the pencil in the editor are the
    same pencil, drawn by the same code — two hand-drawn pencils would be
    two pencils, and the eye notices.
    """
    if kind in _SHARED_ICONS:
        return _vq._icon(kind, size, colour, width)
    from PIL import Image, ImageDraw
    scale = 4
    n = size * scale
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = tuple(colour)
    lw = width * scale
    if kind == "arrow":
        d.line([(n * .20, n * .80), (n * .78, n * .22)], fill=c, width=lw)
        d.polygon([(n * .82, n * .18), (n * .52, n * .22), (n * .78, n * .48)],
                  fill=c)
    elif kind == "box":
        d.rounded_rectangle((n * .16, n * .22, n * .84, n * .78), n * .08,
                            outline=c, width=lw)
    elif kind == "highlight":
        d.line([(n * .16, n * .62), (n * .84, n * .62)], fill=c,
               width=int(lw * 2.6))
        d.line([(n * .26, n * .30), (n * .74, n * .30)], fill=c, width=lw)
    elif kind == "blur":
        for row in range(3):
            for col in range(3):
                if (row + col) % 2:
                    continue
                x0 = n * (.18 + col * .22)
                y0 = n * (.18 + row * .22)
                d.rectangle((x0, y0, x0 + n * .20, y0 + n * .20), fill=c)
    elif kind == "crop":
        d.line([(n * .28, n * .10), (n * .28, n * .72)], fill=c, width=lw)
        d.line([(n * .28, n * .72), (n * .90, n * .72)], fill=c, width=lw)
        d.line([(n * .10, n * .28), (n * .72, n * .28)], fill=c, width=lw)
        d.line([(n * .72, n * .28), (n * .72, n * .90)], fill=c, width=lw)
    elif kind == "save":
        d.rounded_rectangle((n * .16, n * .16, n * .84, n * .84), n * .08,
                            outline=c, width=lw)
        d.rectangle((n * .34, n * .16, n * .66, n * .40), outline=c, width=lw)
        d.rectangle((n * .30, n * .56, n * .70, n * .84), outline=c, width=lw)
    elif kind == "ask":
        d.rounded_rectangle((n * .12, n * .18, n * .88, n * .68), n * .14,
                            outline=c, width=lw)
        d.polygon([(n * .30, n * .66), (n * .30, n * .90), (n * .52, n * .68)],
                  fill=c)
    elif kind == "record":
        d.ellipse((n * .22, n * .22, n * .78, n * .78), fill=c)
    elif kind == "stop":
        d.rounded_rectangle((n * .24, n * .24, n * .76, n * .76), n * .08,
                            fill=c)
    elif kind == "pause":
        d.rounded_rectangle((n * .26, n * .20, n * .42, n * .80), n * .06,
                            fill=c)
        d.rounded_rectangle((n * .58, n * .20, n * .74, n * .80), n * .06,
                            fill=c)
    elif kind == "play":
        d.polygon([(n * .30, n * .18), (n * .30, n * .82), (n * .82, n * .50)],
                  fill=c)
    elif kind == "folder":
        d.line([(n * .12, n * .30), (n * .44, n * .30)], fill=c, width=lw)
        d.rounded_rectangle((n * .12, n * .24, n * .88, n * .78), n * .08,
                            outline=c, width=lw)
    elif kind == "camera":
        d.rounded_rectangle((n * .08, n * .28, n * .92, n * .84), n * .11,
                            outline=c, width=lw)
        d.line([(n * .34, n * .28), (n * .41, n * .16)], fill=c, width=lw)
        d.line([(n * .66, n * .28), (n * .59, n * .16)], fill=c, width=lw)
        d.line([(n * .41, n * .16), (n * .59, n * .16)], fill=c, width=lw)
        d.ellipse((n * .35, n * .40, n * .65, n * .70), outline=c, width=lw)
    elif kind == "timer":
        # A stopwatch, not an hourglass: the shape of a self-timer on every
        # camera anyone has held, and legible at 20 px, which an hourglass
        # is not.
        d.ellipse((n * .14, n * .26, n * .86, n * .94), outline=c, width=lw)
        d.line([(n * .50, n * .60), (n * .50, n * .40)], fill=c, width=lw)
        d.line([(n * .38, n * .12), (n * .62, n * .12)], fill=c, width=lw)
        d.line([(n * .50, n * .12), (n * .50, n * .26)], fill=c, width=lw)
    elif kind == "mirror":
        # Solid on one side of the axis, hollow on the other: the flip is
        # readable without a label because the two halves are the same
        # shape and not the same thing.
        d.line([(n * .50, n * .08), (n * .50, n * .92)], fill=c, width=lw)
        d.polygon([(n * .40, n * .24), (n * .40, n * .76), (n * .10, n * .50)],
                  fill=c)
        d.polygon([(n * .60, n * .24), (n * .60, n * .76), (n * .90, n * .50)],
                  outline=c, width=lw)
    elif kind == "switch":
        d.arc((n * .14, n * .14, n * .86, n * .86), 35, 305, fill=c, width=lw)
        d.polygon([(n * .84, n * .10), (n * .90, n * .40), (n * .60, n * .28)],
                  fill=c)
    else:
        raise ValueError(f"no such icon: {kind}")
    return img.resize((size, size), Image.LANCZOS)


def screen_glyph(size, aspect: float, panes: int = 1, colour=INK,
                 width: int = 2):
    """A little display, drawn in the shape of the display it stands for.

    A row of identical pills with text in them says nothing about which
    monitor is the wide one — the shape does, before the label is read.
    "All screens" is the one with two panes, which is the whole of what it
    means.

    Drawn 4x and shrunk, like every other icon here: Tk antialiases
    nothing and neither does ImageDraw.
    """
    from PIL import Image, ImageDraw
    scale = 4
    box_w, box_h = size[0] * scale, size[1] * scale
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ink = tuple(colour)[:3] + (255,)
    ghost = tuple(colour)[:3] + (110,)
    line = width * scale

    stand = box_h * 0.18
    room_h = box_h - stand
    body_w = min(box_w * 0.94, room_h * max(0.2, aspect))
    body_h = body_w / max(0.2, aspect)
    if body_h > room_h:
        body_h, body_w = room_h, room_h * max(0.2, aspect)
    left = (box_w - body_w) / 2
    top = (room_h - body_h) / 2

    if panes > 1:
        # The second pane sits behind and to one side, dimmer — a stack,
        # not two monitors drawn side by side at half the size, which at
        # 44 px would be two smudges.
        offset = box_w * 0.10
        draw.rounded_rectangle((left + offset, top - body_h * 0.16,
                                left + body_w + offset,
                                top + body_h - body_h * 0.16),
                               body_h * 0.14, outline=ghost, width=line)
    draw.rounded_rectangle((left, top, left + body_w, top + body_h),
                           body_h * 0.14, outline=ink, width=line)
    draw.line([(box_w / 2, top + body_h), (box_w / 2, box_h - stand * 0.45)],
              fill=ink, width=line)
    draw.line([(box_w * 0.34, box_h - stand * 0.4),
               (box_w * 0.66, box_h - stand * 0.4)], fill=ink, width=line)
    return img.resize(size, Image.LANCZOS)


# ------------------------------------------------------------- the editor

TOOLS = (
    ("pen", "pencil", "Draw"),
    ("arrow", "arrow", "Arrow"),
    ("box", "box", "Box"),
    ("highlight", "highlight", "Highlight"),
    ("blur", "blur", "Blur out"),
    ("crop", "crop", "Crop"),
)
ACTIONS = (
    ("copy", "copy", "Copy"),
    ("save", "save", "Save"),
    ("ask", "ask", "Ask"),
)


def bar_layout(tools=TOOLS, actions=ACTIONS) -> dict:
    """Where every chip and button sits inside the toolbar.

    A dict of name -> (x0, y0, x1, y1) in bar-local pixels, plus the bar's
    own size. Pure arithmetic, so the hit test and the painter read the
    SAME numbers — the one bug this shape exists to prevent is a button
    that is drawn a few pixels from where it can be clicked, which is
    invisible in a screenshot and maddening under the hand.
    """
    spots: dict[str, tuple[int, int, int, int]] = {}
    x = BAR_PAD_X
    y = BAR_PAD_Y
    for name, _glyph, _label in tools:
        spots[name] = (x, y, x + CHIP, y + CHIP)
        x += CHIP + GAP
    x += 6
    spots["_sep"] = (x, y + 5, x + 1, y + CHIP - 5)
    x += 6 + GAP
    for name in ("ink", "undo"):
        spots[name] = (x, y, x + CHIP, y + CHIP)
        x += CHIP + GAP
    x += 16
    for name, _glyph, label in actions:
        width = 40 + 8 * len(label)
        spots[name] = (x, y, x + width, y + CHIP)
        x += width + GAP
    spots["close"] = (x, y, x + CHIP, y + CHIP)
    x += CHIP + BAR_PAD_X
    return {"spots": spots, "size": (x, BAR_H)}


def hit(spots: dict, x: int, y: int) -> str | None:
    """Which control is under (x, y), in bar-local pixels."""
    for name, (x0, y0, x1, y1) in spots.items():
        if name.startswith("_"):
            continue
        if x0 <= x <= x1 and y0 <= y <= y1:
            return name
    return None


class ShotWindow:
    """One window over the frozen screen: pick pixels, then work on them.

    THE SELECTOR AND THE EDITOR ARE THE SAME WINDOW, and that is the whole
    interaction design. Windows' own snip takes the picture and then opens
    it somewhere else, at some other size, and you spend the first second
    finding what you just captured. Here the picture never moves: the
    rectangle you dragged lights up where you dragged it, at 1:1, and the
    toolbar arrives underneath it. You draw on the thing itself.

    That is only possible because the screen is FROZEN — the same trick
    the ask card documents. We own every pixel behind the toolbar, so it
    can be real glass, and the selection can be genuinely brighter than
    its surroundings rather than an outline on a dark sheet.

    Runs on the capture thread and blocks until closed. Everything Tk
    happens here and nowhere else.
    """

    def __init__(self, full, *, mode: str = "shot", cfg=None,
                 folder: str = "captures", copy: bool = True,
                 edit: bool = True, on_saved=None, on_ask=None,
                 kind: str = "shot", start_box=None, start_shape=None,
                 saved=None, save: bool = True):
        import tkinter as tk
        self.tk = tk
        self.full = full
        self.mode = mode                 # "shot" | "region"
        self.cfg = cfg
        self.folder = folder
        self.copy = copy
        self.edit = edit
        self.on_saved = on_saved
        self.on_ask = on_ask
        # THE CAMERA KEY COMES IN HERE. A photo has already been framed —
        # by the lens, in the camera window — so there is nothing left to
        # drag: `start_box` says where on the (already doctored) backdrop
        # the picture is, and the window opens straight into the editor on
        # it. `kind` is the first word of the filename and `saved` is the
        # file the camera window already wrote, so the promise is kept
        # once and not twice.
        self.kind = kind                 # "shot" | "photo"
        self.start_box = start_box
        # A lasso that was cut before the editor was ever opened. Dropping
        # it would quietly turn the shape you drew back into a rectangle
        # the first time you clicked Edit on the corner card.
        self.start_shape = start_shape
        self._pre_saved = saved
        # WHETHER THE FILE IS WRITTEN AT ALL. The clipboard is not
        # negotiable and never was; the folder is, and most captures go
        # straight into a chat window and are never opened again. False
        # leaves the picture on the clipboard and puts Save one click away
        # on the corner card — see [capture] always_save.
        self.save = save

        self.root = tk.Tk()
        self.phase = "select"
        self.box: tuple[int, int, int, int] | None = None
        # What the picture WAS, before any cropping. The crop tool can
        # grow back to it and no further — see _crop_stage.
        self.origin_box: tuple[int, int, int, int] | None = None
        self.path: list | None = None
        self.marks: list = []
        self.history: list = []
        self.tool = "pen"
        self.ink = 0
        self.saved_path: Path | None = None
        self.result: dict | None = None
        self.asked = False

        self._vx, self._vy, self._vw, self._vh = virtual_screen()
        self._keep: dict = {}
        self._start: tuple[int, int] | None = None
        self._free: list | None = None
        self._live: list = []            # canvas item ids of the preview
        self._status = ""
        self._status_until = 0.0
        self._closing = False
        self._bar_at: tuple[int, int] | None = None
        self._hint_box: tuple[int, int, int, int] | None = None
        self._hint_at: tuple[int, int] = (0, 0)
        self._hint_line = ""
        self._layout = bar_layout()
        self._hover: str | None = None
        self._dirty = True

        self._build()
        if self.start_box is not None:
            self._begin_at(self.start_box)

    # -- construction --

    def _build(self) -> None:
        from PIL import ImageTk
        root = self.root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry(f"{self._vw}x{self._vh}+{self._vx}+{self._vy}")
        root.configure(bg=SELECT_BG)
        canvas = self.tk.Canvas(root, bg=SELECT_BG, highlightthickness=0,
                                cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas

        # ONE pass over the whole virtual screen: dim it and pull it toward
        # night blue, the same look the ask card freezes to, so the two
        # features are recognisably one app.
        self.dark = self.full.point(_FREEZE_LUT)
        self._keep["dark"] = ImageTk.PhotoImage(self.dark, master=root)
        canvas.create_image(0, 0, anchor="nw", image=self._keep["dark"])

        px, py = root.winfo_pointerx(), root.winfo_pointery()
        self._hint_id = None
        self._chips: dict = {}
        self._chip_hover: str | None = None
        # PAINTED ON THE FIRST TICK, not here. The card is 31 ms of glass
        # and text, and nothing about starting a drag needs it — putting it
        # on the path between the key and a usable overlay only made the
        # key feel slower. One tick later is 15 ms and invisible.
        self._hint_pending = None if self.start_box is not None else (px, py)

        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_move)
        root.bind_all("<Return>", self._on_enter)
        root.bind_all("<KP_Enter>", self._on_enter)

    def _text_ink(self, text: str, pt: float, colour, weight: int = 400,
                  width: int = 900):
        """One line of text, trimmed to its own ink.

        text_pil hands back a picture of the BOX it was given with the
        glyphs at one end — centring that box is how the camera card's
        timer numeral ended up against a chip's left curve. Trim first,
        place second, everywhere.
        """
        glyph = _vq.text_pil(text, width, pt=pt, colour=colour, rtl=False,
                             single=True, weight=weight)
        ink = glyph.getbbox()
        return glyph.crop(ink) if ink else glyph

    def _draw_hint(self, px: int, py: int) -> None:
        """The instructions and the screen chips, as ONE card of glass.

        Two floating grey slabs is what this was, and it looked like two
        floating grey slabs. It can be glass for the same reason the
        editor's toolbar can: the screen is FROZEN, so what is behind the
        card is a photograph we already hold and blurring it is an image
        operation rather than a compositor feature Tk does not have.

        On the monitor the pointer is on, not in the middle of the VIRTUAL
        screen — on a two-monitor desk that is a bezel. Same reason
        visual_qa's selector asks work_area_near first.
        """
        verb = "capture" if self.mode == "shot" else "record"
        if self.mode == "region":
            line = f"Drag the area to {verb}"
        else:
            line = "Drag a box   ·   Shift-drag to lasso"
        self._hint_line = f"{line}   ·   Enter for this screen   ·   Esc cancels"
        hl, ht, hr, hb = work_area_near(px, py)
        self._plan_hint((hl + hr) // 2 - self._vx, ht + 52 - self._vy)
        self._paint_hint()

    def _plan_hint(self, centre_x: int, top_y: int) -> None:
        """Where the card and every chip in it sit, in canvas pixels.

        Arithmetic only, and separate from the painting, so a hover can
        repaint the card without moving anything in it — the same split
        bar_layout makes for the toolbar, and for the same reason.
        """
        screens = monitors()
        entries = []
        for entry in screens:
            left, top, right, bottom = entry["rect"]
            entries.append((entry["label"], (right - left, bottom - top),
                            entry["rect"], entry["primary"], 1))
        if len(screens) > 1:
            vx, vy, vw, vh = virtual_screen()
            entries.append(("All screens", (vw, vh),
                            (vx, vy, vx + vw, vy + vh), False, len(screens)))

        hint = self._text_ink(self._hint_line, 9.5, INK_DIM)
        row = len(entries) * CHIP_W + (len(entries) - 1) * CHIP_GAP
        width = max(row, hint.width) + HINT_PAD * 2
        height = HINT_PAD + hint.height + 14 + CHIP_H + HINT_PAD
        left = max(8, centre_x - width // 2)
        self._hint_box = (left, top_y, left + width, top_y + height)
        self._hint_at = (left + (width - hint.width) // 2, top_y + HINT_PAD)

        x = left + (width - row) // 2
        y = top_y + HINT_PAD + hint.height + 14
        self._chips = {}
        for label, pixels, rect, primary, panes in entries:
            self._chips[label] = {
                "box": (x, y, x + CHIP_W, y + CHIP_H), "target": rect,
                "size": f"{pixels[0]} × {pixels[1]}", "primary": primary,
                "aspect": pixels[0] / max(1, pixels[1]), "panes": panes}
            x += CHIP_W + CHIP_GAP

    def _paint_hint(self) -> None:
        from PIL import Image, ImageTk
        if self._hint_id is False or not self._hint_box:
            return
        canvas = self.canvas
        canvas.delete("hint")
        canvas.delete("chips")
        x0, y0, x1, y1 = self._hint_box
        x0 = max(0, min(x0, self.dark.width - (x1 - x0)))
        y0 = max(0, min(y0, self.dark.height - (y1 - y0)))
        box = (x0, y0, x0 + (x1 - self._hint_box[0]),
               y0 + (y1 - self._hint_box[1]))
        plate = _vq.glass_plate(self.dark, box, radius=HINT_RADIUS)
        plate.alpha_composite(
            self._text_ink(self._hint_line, 9.5, INK_DIM),
            (self._hint_at[0] - self._hint_box[0],
             self._hint_at[1] - self._hint_box[1]))
        for label, chip in self._chips.items():
            self._draw_chip(plate, label, chip,
                            (self._hint_box[0], self._hint_box[1]))
        under = self.dark.crop(box).convert("RGBA")
        under.alpha_composite(plate)
        self._keep["hint"] = ImageTk.PhotoImage(under.convert("RGB"),
                                                master=self.root)
        canvas.create_image(box[0], box[1], anchor="nw",
                            image=self._keep["hint"], tags="hint")

    def _draw_chip(self, plate, label: str, chip: dict, origin) -> None:
        """One screen, drawn as a screen.

        A row of identical pills with text in them says nothing about
        which one is the wide monitor and which is the laptop. A tile with
        a little display on it, IN THAT DISPLAY'S OWN ASPECT RATIO, says
        it before the label is read — and "All screens" is the only one
        with two of them, which is the whole thing it means.
        """
        cx0, cy0, cx1, cy1 = chip["box"]
        x, y = cx0 - origin[0], cy0 - origin[1]
        width, height = cx1 - cx0, cy1 - cy0
        hot = (label == self._chip_hover)
        fill = (110, 160, 235, 92) if hot else (255, 255, 255, 20)
        edge = (150, 195, 255, 210) if hot else (255, 255, 255, 46)
        tile = _vq.rr_layer((width, height), 12, fill, edge)
        glyph = screen_glyph((46, 31), chip["aspect"], chip["panes"],
                             colour=INK if hot else INK_DIM)
        tile.alpha_composite(glyph, ((width - glyph.width) // 2, 9))
        name = self._text_ink(label, 9.0, INK if hot else INK_DIM,
                              weight=600)
        tile.alpha_composite(name, ((width - name.width) // 2, height - 28))
        size = self._text_ink(chip["size"], 7.8,
                              INK_DIM if hot else INK_FAINT)
        tile.alpha_composite(size, ((width - size.width) // 2, height - 15))
        if chip["primary"]:
            # A dot, not the word "primary": the row is read at a glance
            # and one of these is always the one everything opens on.
            dot = _vq.rr_layer((5, 5), 2, (150, 195, 255, 220))
            tile.alpha_composite(dot, (width - 12, 8))
        plate.alpha_composite(tile, (x, y))

    def _drop_hint(self) -> None:
        if self._hint_id is not False:
            self.canvas.delete("hint")
            self.canvas.delete("chips")
            self._hint_id = False
            self._chips = {}
            self._hint_box = None

    # -- the selection phase --

    def _on_press(self, event) -> None:
        if self.phase == "edit":
            return self._edit_press(event)
        chosen = self._chip_under(event.x, event.y)
        if chosen is not None:
            # A whole screen, chosen by name. No drag ever starts, so the
            # click is spent here and not remembered as a 1x1 rectangle.
            #
            # READ THE TARGET FIRST. _drop_hint clears the chip table, so
            # resolving the label afterwards is a KeyError on every click —
            # which is exactly what the first version did.
            target = self._chips_target(chosen)
            self._drop_hint()
            return self._chose(target, None)
        self._start = (event.x_root, event.y_root)
        # SHIFT AT THE MOMENT OF THE PRESS decides the shape, decided once
        # so the gesture cannot change its mind halfway. The same rule the
        # ask card's selector uses, because it is the same hand.
        self._free = ([(event.x_root, event.y_root)]
                      if (event.state & 0x0001) and self.mode == "shot"
                      else None)
        self._drop_hint()

    def _on_drag(self, event) -> None:
        if self.phase == "edit":
            return self._edit_drag(event)
        if self._start is None:
            return
        if self._free is not None:
            last = self._free[-1]
            if abs(last[0] - event.x_root) + abs(last[1] - event.y_root) >= 3:
                self._free.append((event.x_root, event.y_root))
                self._paint_free(self._free)
            return
        self._paint_box(normalize_bbox(self._start[0], self._start[1],
                                       event.x_root, event.y_root))

    def _on_release(self, event) -> None:
        if self.phase == "edit":
            return self._edit_release(event)
        if self._start is None:
            return self.close()
        if self._free is not None:
            points = self._free
            if len(points) < 6:
                return self.close()          # a scribble too short to mean it
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                return self.close()
            return self._chose(box, points)
        left, top, right, bottom = normalize_bbox(
            self._start[0], self._start[1], event.x_root, event.y_root)
        # Click-without-drag cancels: a tap is how you change your mind
        # about the dimming, not a request to capture one pixel.
        if right - left < 8 or bottom - top < 8:
            return self.close()
        self._chose((left, top, right, bottom), None)

    def _on_enter(self, _event=None) -> None:
        """Enter = this whole monitor. The commonest capture there is, and
        without it the only way to get one is a drag from corner to corner
        that is impossible to land exactly."""
        if self.phase != "select":
            return
        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
        self._drop_hint()
        self._chose(monitor_near(px, py), None)

    def _on_move(self, event) -> None:
        if self.phase == "select":
            hot = self._chip_under(event.x, event.y)
            if hot != self._chip_hover:
                self._chip_hover = hot
                self.canvas.config(cursor="hand2" if hot else "crosshair")
                self._paint_hint()
            return
        if self.phase != "edit" or self._bar_at is None:
            return
        bx, by = self._bar_at
        spots = self._layout["spots"]
        name = hit(spots, event.x + self._vx - bx, event.y + self._vy - by)
        if name != self._hover:
            self._hover = name
            self._dirty = True

    def _chip_under(self, x: int, y: int) -> str | None:
        """Which screen chip is under a canvas point, if any."""
        for label, chip in self._chips.items():
            x0, y0, x1, y1 = chip["box"]
            if x0 <= x <= x1 and y0 <= y <= y1:
                return label
        return None

    def _chips_target(self, label: str) -> tuple[int, int, int, int]:
        return self._chips[label]["target"]

    def _paint_box(self, box) -> None:
        """The bright hole: the SAME pixels, undimmed, out of the picture
        we already hold. Measured under a millisecond at 900x450, so no
        throttle — the first design assumed one and did not need it."""
        from PIL import ImageTk
        left, top, right, bottom = box
        self.canvas.delete("sel")
        if right - left < 2 or bottom - top < 2:
            return
        crop = self.full.crop((left - self._vx, top - self._vy,
                               right - self._vx, bottom - self._vy))
        self._keep["bright"] = ImageTk.PhotoImage(crop, master=self.root)
        self.canvas.create_image(left - self._vx, top - self._vy, anchor="nw",
                                 image=self._keep["bright"], tags="sel")
        self.canvas.create_rectangle(left - self._vx, top - self._vy,
                                     right - self._vx, bottom - self._vy,
                                     outline=ACCENT, width=2, tags="sel")
        self._readout(box)

    def _paint_free(self, points) -> None:
        """The lasso, composited on its BOUNDING BOX only.

        A polygon fill over the whole virtual screen would be 6.45 M
        pixels per mouse move; over the box it is whatever has been drawn
        so far, which starts tiny and is still small at the end.
        """
        from PIL import Image, ImageDraw, ImageTk
        if len(points) < 3:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        left, top = min(xs), min(ys)
        right, bottom = max(xs) + 1, max(ys) + 1
        self.canvas.delete("sel")
        if right - left < 2 or bottom - top < 2:
            return
        width, height = right - left, bottom - top
        crop = self.full.crop((left - self._vx, top - self._vy,
                               right - self._vx, bottom - self._vy))
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon(_shift(points, left, top), fill=255)
        lit = Image.composite(crop, crop.point(_FREEZE_LUT), mask)
        self._keep["bright"] = ImageTk.PhotoImage(lit, master=self.root)
        self.canvas.create_image(left - self._vx, top - self._vy, anchor="nw",
                                 image=self._keep["bright"], tags="sel")
        self.canvas.create_line(
            *[c for p in points for c in (p[0] - self._vx, p[1] - self._vy)],
            fill=ACCENT, width=2, tags="sel")
        self._readout((left, top, right, bottom))

    def _readout(self, box) -> None:
        left, top, right, bottom = box
        y = bottom - self._vy + 6
        if y > self._vh - 24:
            y = bottom - self._vy - 22
        self.canvas.create_text(right - self._vx - 6, y,
                                text=selection_readout(box), fill=FG,
                                anchor="ne",
                                font=(_vq._pick_face(), 9, "bold"),
                                tags="sel")

    def _chose(self, box, path) -> None:
        """The drag is over. Either hand the region back, or start editing."""
        bounds = (self._vx, self._vy, self._vx + self._vw, self._vy + self._vh)
        self.box = clamp_box(box, bounds)
        self.origin_box = self.box
        self.path = path
        # THE DRAG IS OVER, so nothing may still be pending from it. It
        # was not, and that was a real bug: the selection drag ends here
        # without clearing `_start`, so the very next press — the first
        # toolbar button you reach for — released into _edit_release with
        # the selection's own start point still sitting there and drew a
        # stroke from it, or, with crop picked, silently re-cropped the
        # picture to somewhere under the toolbar. Once per capture,
        # always on the first click, which is why it looked like the tool
        # itself misbehaving.
        self._start = None
        self._free = None
        if self.mode == "region":
            self.result = {"box": self.box}
            return self.close()
        self._first_save()
        if not self.edit:
            # The editor is an OFFER, never a step. When it is not being
            # taken here, everything needed to offer it LATER — from a
            # corner card, five seconds from now — goes back with the
            # result: the rectangle, the lasso, the file if one was
            # written, and the picture itself.
            self.result = {"box": self.box, "shape": self.path,
                           "path": self.saved_path,
                           "image": self.picture()}
            return self.close()
        self.phase = "edit"
        self.canvas.config(cursor="crosshair")
        self._dirty = True

    def _begin_at(self, box) -> None:
        """Open straight into the editor on a picture we were handed.

        The camera key's way in. Everything after this point is identical
        to a screenshot — the same toolbar, the same undo, the same Ask —
        because by the time a picture is on the backdrop the editor cannot
        tell, and should not be able to tell, which lens it came through.

        The one difference is who kept the promise. A screenshot is saved
        and copied by _first_save the instant the drag ends; a photo was
        already saved and copied by the camera window at the instant the
        shutter fired, which is earlier and is where it belongs. So the
        path is adopted rather than written again — otherwise one press of
        one key would leave two identical files in the folder.
        """
        bounds = (self._vx, self._vy, self._vx + self._vw,
                  self._vy + self._vh)
        self.box = clamp_box(box, bounds)
        self.origin_box = self.box
        self.path = self.start_shape
        if self._pre_saved is not None:
            self.saved_path = self._pre_saved
            self.say(f"{'copied · ' if self.copy else ''}"
                     f"{self.saved_path.name}")
        else:
            self._first_save()
        if not self.edit:
            return self.close()
        self.phase = "edit"
        self.canvas.config(cursor="crosshair")
        self._dirty = True

    # -- the editing phase --

    def _first_save(self) -> None:
        """Save and copy the moment the drag ends, before anything is edited.

        This is the Win+Shift+S promise and it is not negotiable: the
        capture is on the clipboard and on disk by the time the hand has
        left the mouse, and the editor is an OFFER, not a step you have to
        complete. Closing it with Esc loses nothing.
        """
        image = self.picture()
        if self.save:
            try:
                self.saved_path = save_image(image, self.folder,
                                             kind=self.kind)
            except Exception as e:
                log.exception("could not save the screenshot")
                self.say(f"could not save: {e}", ttl_ms=6000)
                return
        copied = copy_image(image) if self.copy else False
        where = self.saved_path.name if self.saved_path else "not saved"
        self.say(f"{'copied · ' if copied else ''}{where}")
        log.info("screenshot %d×%d %s%s", image.width, image.height,
                 f"saved to {self.saved_path}" if self.saved_path
                 else "kept on the clipboard only",
                 " and copied" if copied else "")
        if self.on_saved is not None:
            self.on_saved(self.saved_path)

    def picture(self):
        """What the user is looking at, as a picture. One function for the
        screen and for the file, so the two cannot disagree."""
        return render_shot(self.full, self.box, self.marks, self.path,
                           screen_origin=(self._vx, self._vy))

    def say(self, text: str, ttl_ms: int = 4200) -> None:
        self._status = text
        self._status_until = time.monotonic() + ttl_ms / 1000.0
        self._dirty = True

    def _push_history(self) -> None:
        """Remember the WHOLE state, not the change.

        A crop and a stroke are different kinds of edit and undo must be
        one button; storing states rather than inverse operations is what
        makes that true without a case per tool. 40 deep, which is far
        more than anyone annotates in one sitting and still nothing —
        each entry is a rectangle, a polygon and a few point lists.
        """
        self.history.append((self.box, self.path, list(self.marks)))
        if len(self.history) > 40:
            del self.history[0]

    def _edit_press(self, event) -> None:
        x, y = event.x_root, event.y_root
        if self._bar_at is not None:
            bx, by = self._bar_at
            name = hit(self._layout["spots"], x - bx, y - by)
            if name is not None:
                # A press on the toolbar is not the beginning of a
                # stroke, and must not be able to end one either — see
                # _chose for the bug this second line closes.
                self._start = None
                self._free = None
                return self._activate(name)
        # The CROP may be started anywhere it may end, which after a crop
        # is a bigger rectangle than the picture — that is the whole point
        # of being able to grow one back. Every other tool draws ON the
        # picture, so for those a click on the dim is still ignored.
        left, top, right, bottom = (self._crop_stage()
                                    if self.tool == "crop" else self.box)
        if not (left <= x <= right and top <= y <= bottom):
            return                       # a click on the dim: ignored
        self._start = (x, y)
        self._free = None
        self._live = []

    def _edit_drag(self, event) -> None:
        if self._start is None:
            return
        x, y = event.x_root, event.y_root
        colour = "#%02x%02x%02x" % INKS[self.ink][1]
        for item in self._live:
            self.canvas.delete(item)
        self._live = []
        sx, sy = self._start
        cx0, cy0 = sx - self._vx, sy - self._vy
        cx1, cy1 = x - self._vx, y - self._vy
        # THE CANVAS ITEM IS A PREVIEW AND NOTHING ELSE. The picture is
        # rebuilt from points when the stroke commits — never read back
        # off the screen, which races the topmost window and returns
        # black (visual_qa.py records paying for that one).
        if self.tool == "pen":
            self._free = (self._free or [self._start])
            if abs(self._free[-1][0] - x) + abs(self._free[-1][1] - y) >= 2:
                self._free.append((x, y))
            flat = [c for p in self._free
                    for c in (p[0] - self._vx, p[1] - self._vy)]
            if len(flat) >= 4:
                # smooth + round joins, not PIL's joint= — that keyword
                # belongs to ImageDraw and Tk's canvas answers it with
                # 'unknown option "-joint"'. The two draw the same stroke
                # through APIs that only look alike.
                self._live = [self.canvas.create_line(
                    *flat, fill=colour, width=PEN_W, capstyle="round",
                    joinstyle="round", smooth=True, tags="ink")]
        elif self.tool == "highlight":
            self._free = (self._free or [self._start])
            if abs(self._free[-1][0] - x) + abs(self._free[-1][1] - y) >= 2:
                self._free.append((x, y))
            flat = [c for p in self._free
                    for c in (p[0] - self._vx, p[1] - self._vy)]
            if len(flat) >= 4:
                self._live = [self.canvas.create_line(
                    *flat, fill=colour, width=HIGHLIGHT_W, capstyle="round",
                    joinstyle="round", smooth=True, tags="ink")]
        elif self.tool == "arrow":
            self._live = [self.canvas.create_line(
                cx0, cy0, cx1, cy1, fill=colour, width=PEN_W, arrow="last",
                arrowshape=tk_arrowshape(), tags="ink")]
        elif self.tool in ("box", "blur", "crop"):
            dash = (5, 4) if self.tool == "crop" else None
            outline = FG if self.tool == "crop" else colour
            self._live = [self.canvas.create_rectangle(
                cx0, cy0, cx1, cy1, outline=outline, width=BOX_W, dash=dash,
                tags="ink")]

    def _edit_release(self, event) -> None:
        if self._start is None:
            return
        start, self._start = self._start, None
        points = self._free or [start, (event.x_root, event.y_root)]
        self._free = None
        for item in self._live:
            self.canvas.delete(item)
        self._live = []
        end = (event.x_root, event.y_root)
        if self.tool in ("arrow", "box", "blur", "crop"):
            points = [start, end]
        if (self.tool != "crop"
                and abs(end[0] - start[0]) + abs(end[1] - start[1]) < 4
                and len(points) < 4):
            return                       # a click, not a stroke
        if self.tool == "crop":
            box = clamp_box((start[0], start[1], end[0], end[1]),
                            self._crop_stage())
            if box[2] - box[0] < 16 or box[3] - box[1] < 16:
                return
            self._push_history()
            self._crop_to(box)
            return
        self._push_history()
        self.marks.append({"kind": self.tool, "points": list(points),
                           "colour": INKS[self.ink][1]})
        self._dirty = True

    def _crop_stage(self) -> tuple[int, int, int, int]:
        """The rectangle the crop tool is allowed to work in.

        FOR A SCREEN CAPTURE, THE WHOLE FROZEN SCREEN. Cropping is the one
        edit that throws pixels away and the one edit everybody
        overshoots, and on a frozen screen there is nothing to be sorry
        about: every pixel is still there. So the crop tool is not "make
        this smaller", it is TAKE THE SHOT AGAIN without pressing the key
        again — move the rectangle sideways, make it bigger, put it
        somewhere else on the desktop entirely.

        A CAMERA PHOTO stops at the photo. Behind that one is not more of
        the shot: it is the desktop the camera card happened to be sitting
        on, and re-framing onto it would hand you a picture of your own
        wallpaper. There the tool means what it used to — inward, and back
        out to what you cut.
        """
        if self.kind == "photo":
            return self.origin_box or self.box
        return (self._vx, self._vy, self._vx + self._vw, self._vy + self._vh)

    def _whole_screen(self) -> tuple[int, int, int, int]:
        return (self._vx, self._vy, self._vx + self._vw, self._vy + self._vh)

    def _crop_to(self, box) -> None:
        """Re-frame the shot — inward, or back outward.

        The marks keep their VIRTUAL-SCREEN coordinates through this, so a
        crop is one number changing and an undo puts the rectangle back
        with every mark still where it was drawn — including the ones the
        crop had cut off the edge. That is also why growing one back is
        almost free: the ink that was outside the rectangle was never
        deleted, only left out of the render, so it comes back with the
        pixels it was drawn on.
        """
        before = self.box
        self.box = box
        self.path = None                 # a crop of a lasso is a rectangle
        grew = (box[2] - box[0]) * (box[3] - box[1]) >                (before[2] - before[0]) * (before[3] - before[1])
        self.say(f"{'back out to' if grew else 'cropped to'} "
                 f"{selection_readout(box)}")
        self._dirty = True

    def _activate(self, name: str) -> None:
        if name in dict((t[0], t) for t in TOOLS):
            self.tool = name
            self.say({"pen": "draw", "arrow": "drag an arrow",
                      "box": "drag a box", "highlight": "drag to highlight",
                      "blur": "drag over what should not be readable",
                      "crop": self._crop_hint()}[name])
            self._dirty = True
            return
        if name == "ink":
            self.ink = (self.ink + 1) % len(INKS)
            self.say(INKS[self.ink][0])
            self._dirty = True
            return
        if name == "undo":
            state, self.history = undo_step(self.history)
            if state is None:
                return self.say("nothing to undo")
            self.box, self.path, marks = state
            self.marks = list(marks)
            self._dirty = True
            return
        if name == "copy":
            # ON A THREAD, because this is a Tk button handler and the
            # clipboard is a queue shared with the whole process now
            # (injector._board_lock). The longest thing on that queue — a
            # lookup that found nothing selected — holds it for up to
            # 2.1 s, and an editor that stopped repainting for two seconds
            # because somebody pressed the lookup key would read as a
            # hang. The same shape popup.py's copy button has always had.
            picture = self.picture()
            self.say("copied", ttl_ms=FLASH_MS)
            threading.Thread(target=copy_image, args=(picture,),
                             daemon=True, name="capture-copy").start()
            return
        if name == "save":
            return self._save_again()
        if name == "ask":
            return self._ask()
        if name == "close":
            return self.close()

    def _save_again(self) -> None:
        """Write the edited picture over the file this shot already made.

        OVER, not beside. One drag makes one file — a folder that grows a
        new png every time you press Save is a folder nobody can find
        anything in, and the first save happened without being asked for.
        """
        image = self.picture()
        try:
            if self.saved_path is None:
                self.saved_path = save_image(image, self.folder,
                                             kind=self.kind)
            else:
                image.save(self.saved_path, "PNG")
        except Exception as e:
            log.exception("could not save the edited screenshot")
            return self.say(f"could not save: {e}", ttl_ms=6000)
        if self.copy:
            copy_image(image)
        self.say(f"saved · {self.saved_path.name}", ttl_ms=FLASH_MS * 2)
        log.info("screenshot updated: %s", self.saved_path)

    def _ask(self) -> None:
        """Hand the picture to the ask card and get out of its way.

        The two features are one gesture apart and this is the bridge: the
        pixels you just marked up are exactly the pixels worth asking
        about. Everything the ask card does about privacy — the upload
        gate, the local-first chain — applies unchanged, because it is
        that module doing the asking.
        """
        if self.on_ask is None:
            return self.say("ask-the-screen is switched off")
        self.asked = True
        self.result = {"ask": (self.picture(), self.box)}
        self.close()

    # -- painting --

    def _paint(self) -> None:
        from PIL import Image, ImageDraw, ImageFilter, ImageTk
        if self.phase != "edit" or self.box is None:
            return
        canvas = self.canvas
        canvas.delete("sel")
        left, top, right, bottom = self.box
        shot = self.picture()
        # While the crop tool is up you may drag outside the picture, so
        # something outside it has to be visible. On a frozen screen that
        # is the whole dimmed desktop, which is already painted and costs
        # nothing — the halo stays around the SELECTION and the rest of
        # the screen is the same canvas the first drag was made on. Only a
        # camera photo needs the faint layer, because there the reachable
        # part is a rectangle rather than everything.
        back = None
        if self.tool == "crop":
            stage = self._crop_stage()
            if stage != self._whole_screen() and stage != self.box:
                back = stage
        stage = back or self.box

        # The lit selection, its halo and its edge, computed on a CROP
        # around the rectangle rather than over the whole screen: a
        # full-screen blur here was 500 ms of the ask card's first draft.
        pad = 46
        hx0 = max(0, stage[0] - self._vx - pad)
        hy0 = max(0, stage[1] - self._vy - pad)
        hx1 = min(self.dark.width, stage[2] - self._vx + pad)
        hy1 = min(self.dark.height, stage[3] - self._vy + pad)
        local = self.dark.crop((hx0, hy0, hx1, hy1)).convert("RGBA")
        lw, lh = local.size
        ox, oy = left - self._vx - hx0, top - self._vy - hy0
        ex, ey = ox + (right - left), oy + (bottom - top)
        halo = Image.new("L", (lw, lh), 0)
        ImageDraw.Draw(halo).rounded_rectangle(
            (stage[0] - self._vx - hx0 - 3, stage[1] - self._vy - hy0 - 3,
             stage[2] - self._vx - hx0 + 3, stage[3] - self._vy - hy0 + 3),
            14, outline=255, width=16)
        halo = halo.filter(ImageFilter.GaussianBlur(9)).point(
            lambda v: int(v * .45))
        local.alpha_composite(Image.merge("RGBA", (
            Image.new("L", (lw, lh), 86), Image.new("L", (lw, lh), 156),
            Image.new("L", (lw, lh), 245), halo)))
        if back is not None:
            self._paint_recoverable(local, back, (hx0, hy0))
        local.alpha_composite(shot.convert("RGBA"), (ox, oy))
        edge = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle((ox - 2, oy - 2, ex + 1, ey + 1),
                                               13,
                                               outline=(86, 156, 245, 235),
                                               width=2)
        local.alpha_composite(edge)

        scene = local.convert("RGB")
        self._keep["stage"] = ImageTk.PhotoImage(scene, master=self.root)
        canvas.create_image(hx0, hy0, anchor="nw", image=self._keep["stage"],
                            tags="sel")
        self._paint_bar()
        canvas.tag_raise("ink")

    def _crop_hint(self) -> str:
        if self._crop_stage() == self._whole_screen():
            return "drag anywhere to re-frame the shot"
        if self._crop_stage() != self.box:
            return "drag the part to keep — or back out to what you cut"
        return "drag the part to keep"

    def _paint_recoverable(self, local, stage, offset) -> None:
        """The part you already cut, shown faintly enough to aim at.

        Without it the crop tool would be asking you to drag into the
        dark and hope. The pixels are real — the frozen screen still has
        them and the marks were never deleted, only left out of the
        render — so this is the same picture at CROP_BACK of its
        brightness, and the live rectangle then lands on something you
        can see.

        Painted UNDER the lit selection rather than around it, because a
        ring is four rectangles and one paste is one paste.
        """
        from PIL import Image
        hx0, hy0 = offset
        back = render_shot(self.full, stage, self.marks, None,
                           screen_origin=(self._vx, self._vy)).convert("RGB")
        dim = self.dark.crop((stage[0] - self._vx, stage[1] - self._vy,
                              stage[2] - self._vx, stage[3] - self._vy))
        faded = Image.blend(dim.convert("RGB"), back, CROP_BACK)
        local.alpha_composite(faded.convert("RGBA"),
                              (stage[0] - self._vx - hx0,
                               stage[1] - self._vy - hy0))

    def _paint_bar(self) -> None:
        """The toolbar: one glass plate with everything painted into it.

        Glass is possible here for exactly one reason — the screen behind
        it is a photograph we took, so blurring what is behind the window
        is an image operation rather than a compositor feature Tk does not
        have. The clip bar, which floats over a live screen, cannot do
        this and does not try.
        """
        from PIL import Image, ImageTk
        bw, bh = self._layout["size"]
        screen = monitor_near((self.box[0] + self.box[2]) // 2,
                              (self.box[1] + self.box[3]) // 2)
        bx, by = plan_bar(self.box, (bw, bh), screen)
        # Canvas coordinates, then clamped into the SURFACE rather than the
        # monitor: plan_bar has already said which monitor, and this is the
        # last line of defence against a paste that would raise instead of
        # merely looking wrong.
        lx = max(0, min(bx - self._vx, self.dark.width - bw))
        ly = max(0, min(by - self._vy, self.dark.height - bh))
        self._bar_at = (lx + self._vx, ly + self._vy)

        plate = _vq.glass_plate(self.dark, (lx, ly, lx + bw, ly + bh),
                                radius=BAR_RADIUS)
        self._draw_bar_content(plate)
        under = self.dark.crop((lx, ly, lx + bw, ly + bh)).convert("RGBA")
        under.alpha_composite(plate)
        self._keep["bar"] = ImageTk.PhotoImage(under.convert("RGB"),
                                               master=self.root)
        self.canvas.create_image(lx, ly, anchor="nw", image=self._keep["bar"],
                                 tags="sel")

    def _draw_bar_content(self, plate) -> None:
        from PIL import Image
        spots = self._layout["spots"]
        glyphs = dict((name, glyph) for name, glyph, _l in TOOLS)
        glyphs.update((name, glyph) for name, glyph, _l in ACTIONS)
        labels = dict((name, label) for name, _g, label in ACTIONS)

        for name, (x0, y0, x1, y1) in spots.items():
            if name == "_sep":
                plate.alpha_composite(
                    Image.new("RGBA", (max(1, x1 - x0), y1 - y0),
                              (255, 255, 255, 40)), (x0, y0))
                continue
            selected = (name == self.tool)
            hovered = (name == self._hover)
            if name in labels:
                fill = (86, 156, 245, 190) if hovered else (255, 255, 255, 26)
                outline = (255, 255, 255, 70) if hovered else (255, 255, 255, 52)
            elif selected:
                fill, outline = (86, 156, 245, 175), (255, 255, 255, 90)
            elif hovered:
                fill, outline = (255, 255, 255, 46), (255, 255, 255, 70)
            else:
                fill, outline = (255, 255, 255, 20), (255, 255, 255, 40)
            radius = 11 if name in labels else CHIP // 2
            plate.alpha_composite(
                _vq.rr_layer((x1 - x0, y1 - y0), radius, fill, outline),
                (x0, y0))
            if name == "ink":
                swatch = _vq.rr_layer((14, 14), 7, INKS[self.ink][1] + (255,),
                                      (255, 255, 255, 130))
                plate.alpha_composite(swatch, (x0 + (CHIP - 14) // 2,
                                               y0 + (CHIP - 14) // 2))
                continue
            glyph_name = glyphs.get(name, name)
            colour = INK if (selected or hovered) else INK_DIM
            if name in labels:
                text = _vq.text_pil(labels[name], x1 - x0 - 30, pt=10.5,
                                    colour=INK, rtl=False, single=True,
                                    weight=600)
                mark = icon(glyph_name, 17, colour=INK, width=2)
                plate.alpha_composite(mark, (x0 + 11, y0 + (CHIP - 17) // 2))
                plate.alpha_composite(text, (x0 + 32,
                                             y0 + (CHIP - text.height) // 2))
                continue
            mark = icon(glyph_name, 19, colour=colour, width=2)
            plate.alpha_composite(mark, (x0 + (CHIP - 19) // 2,
                                         y0 + (CHIP - 19) // 2))

        line = self._status if time.monotonic() < self._status_until else ""
        if not line:
            line = (f"{selection_readout(self.box)}   ·   "
                    f"{INKS[self.ink][0]}   ·   Esc closes")
        text = _vq.text_pil(line, plate.width - 2 * BAR_PAD_X, pt=9.5,
                            colour=INK_FAINT, rtl=False, single=True)
        plate.alpha_composite(text, (BAR_PAD_X, BAR_H - 26))

    # -- the pump --

    def close(self) -> None:
        self._closing = True

    def run(self) -> dict | None:
        """Drive the window until it closes. Returns what happened."""
        root = self.root
        try:
            root.update_idletasks()
            root.update()
            _vq.take_foreground(root, alt_tap=False)
            if self._hint_pending is not None and self._hint_id is not False:
                where, self._hint_pending = self._hint_pending, None
                self._draw_hint(*where)
            _user32.GetAsyncKeyState(0x1B)     # prime, discard
            # A key ALREADY down when the window opens is not a cancel —
            # see esc_held for the afternoon that bought this line.
            held = esc_held()
            if held:
                log.info("esc is held down as this overlay opens — it will "
                         "stay up until esc is released and pressed again")
            while not self._closing:
                # ESCAPE IS READ, NOT RECEIVED — a borderless topmost
                # overlay does not get the keyboard focus for free, and
                # taking it with the Alt tap arms the menu bar of whatever
                # is underneath and eats the click that starts the drag.
                # Both halves of GetAsyncKeyState, or a tap between two
                # ticks is lost. Same call, same reasons, as the selector.
                pressed = _user32.GetAsyncKeyState(0x1B)
                down, fresh = bool(pressed & 0x8000), bool(pressed & 0x0001)
                if (down or fresh) and not held:
                    break
                held = down
                if self._dirty:
                    self._dirty = False
                    self._paint()
                elif (self._status and time.monotonic() > self._status_until):
                    self._status = ""
                    self._dirty = True
                try:
                    root.update()
                except self.tk.TclError:
                    break
                time.sleep(_TICK_S)
        finally:
            self._keep.clear()
            try:
                root.destroy()
            except Exception:
                pass
            # Frees the images. It cannot free the INTERPRETER — the
            # caller still holds this object — so the collect that
            # satisfies the Tcl_AsyncDelete rule is the one in
            # Controller._flow, after the last reference is gone.
            gc.collect()
        return self.result


# -------------------------------------------------------------- the clip bar

class ClipBar:
    """The little window that says a recording is happening.

    THREE SHAPES, ONE WINDOW, and the sequence is the design. It opens as a
    card that says **Recording started** — the announcement the owner asked
    for, and the thing every recorder worth using does, because the failure
    mode of a screen recorder is not knowing whether it is running. After a
    couple of seconds it shrinks to a pill in a corner that is a red dot and
    a clock and nothing else. Put the pointer on it and the controls come
    back.

    The corner matters more than it sounds. Beside the region, the
    indicator moves whenever the region does and sits over whatever you
    were about to click; in a corner it is somewhere you learn to glance,
    and it is the same somewhere every time. `[capture] timer_corner`
    chooses which, or `"off"` for no indicator at all — the recording is
    still announced, and the hotkey still stops it.

    NOT GLASS, and the reason is worth writing down: the glass in this app
    is painted from a photograph of the screen behind the window, and this
    window floats over a screen that is still moving. There is nothing to
    photograph. So it is honest card stock in the app's own palette with
    SetWindowRgn corners — the shape popup.py uses for the same reason.

    None of it appears in the recording (WDA_EXCLUDEFROMCAPTURE, measured
    0 of 60000 pixels), which is what lets it sit in a corner that may be
    inside the region being recorded.
    """

    def __init__(self, recorder: ScreenRecorder, *, on_stop=None,
                 on_discard=None, on_mic=None, corner: str = "bottom-right",
                 announce: bool = True, stop_key: str = ""):
        import tkinter as tk
        self.tk = tk
        self.recorder = recorder
        self.on_stop = on_stop
        self.on_discard = on_discard
        self.on_mic = on_mic
        self.corner = corner if corner in CORNERS else "bottom-right"
        self.announce = announce
        self.stop_key = stop_key
        self.root = tk.Tk()
        self.done = threading.Event()
        self.started = time.monotonic()
        self._drag: tuple[int, int] | None = None
        self._moved = False          # dragged by hand: stop re-anchoring it
        self._keep: dict = {}
        self._frame = None
        self._hovering = False
        self._left_at = 0.0
        self._shape: tuple[str, int, int] | None = None
        self._build()

    # -- construction --

    def _anchor(self) -> tuple[int, int, int, int]:
        """The WORK area the pill is cornered in.

        The monitor the recorded region is mostly on, not the primary and
        not the virtual screen: an indicator for a recording happening on
        the left monitor belongs on the left monitor.
        """
        left, top, right, bottom = self.recorder.box
        return work_area_near((left + right) // 2, (top + bottom) // 2)

    def _build(self) -> None:
        root = self.root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=CARD)
        canvas = self.tk.Canvas(root, bg=CARD, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas
        canvas.bind("<ButtonPress-1>", self._press)
        canvas.bind("<B1-Motion>", self._move)
        canvas.bind("<ButtonRelease-1>", self._release)
        canvas.bind("<Enter>", self._enter)
        canvas.bind("<Leave>", self._leave)
        self._apply_shape(force=True)
        hide_from_capture(root)
        self._build_frame()

    def _build_frame(self) -> None:
        """A thin accent frame around what is being recorded.

        Its own window with a hole cut in it (SetWindowRgn of the outside
        minus the inside) so it is a frame rather than a pane, made
        click-through so it never eats a click on the thing you are
        recording, and hidden from capture so it does not end up IN the
        recording it is describing.

        Drawn OUTSIDE the region as well as excluded from it — belt and
        braces, and it means the border is visible even on the one machine
        where the affinity call might not be honoured.
        """
        left, top, right, bottom = self.recorder.box
        pad = CLIP_FRAME_W
        frame = self.tk.Toplevel(self.root)
        frame.overrideredirect(True)
        frame.attributes("-topmost", True)
        frame.configure(bg=ACCENT)
        frame.geometry(f"{right - left + pad * 2}x{bottom - top + pad * 2}"
                       f"+{left - pad}+{top - pad}")
        frame.update_idletasks()
        try:
            gdi32, user32 = _gdi32, _user32
            gdi32.CreateRectRgn.restype = ctypes.c_void_p
            width = right - left + pad * 2
            height = bottom - top + pad * 2
            outer = gdi32.CreateRectRgn(0, 0, width, height)
            inner = gdi32.CreateRectRgn(pad, pad, width - pad, height - pad)
            gdi32.CombineRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_int]
            gdi32.CombineRgn(ctypes.c_void_p(outer), ctypes.c_void_p(outer),
                             ctypes.c_void_p(inner), 4)      # RGN_DIFF
            gdi32.DeleteObject(ctypes.c_void_p(inner))
            hwnd = int(frame.winfo_id())
            target = user32.GetParent(hwnd) or hwnd
            user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            w.BOOL]
            user32.SetWindowRgn(ctypes.c_void_p(target),
                                ctypes.c_void_p(outer), True)
        except Exception:
            log.debug("could not cut the recording frame", exc_info=True)
        click_through(frame)
        hide_from_capture(frame)
        self._frame = frame

    # -- shape --

    def phase(self) -> str:
        """announce -> timer -> gone, and hover any time the pointer is on it.

        `timer_corner = "off"` means the pill never appears — but the
        announcement still does, because "is it recording?" has to be
        answerable at least once. After it, the window withdraws and only
        the frame around the region is left.
        """
        if self.corner == "off":
            if self.announce and (time.monotonic() - self.started
                                  < ANNOUNCE_S):
                return "announce"
            return "hidden"
        if not self.announce and not self._hovering:
            return "timer"
        return bar_phase(time.monotonic() - self.started, self._hovering)

    def _label(self) -> str:
        label = elapsed_readout(self.recorder.elapsed)
        if self.recorder.paused:
            label += "  paused"
        elif self.recorder.has_audio and self.recorder.muted:
            label += "  muted"
        return label

    def _layout(self) -> tuple[str, int, int, dict]:
        """(phase, width, height, spots) — one source for paint and hit.

        The same discipline bar_layout keeps for the editor's toolbar: a
        control drawn a few pixels from where it can be pressed is
        invisible in a screenshot and maddening under the hand.
        """
        phase = self.phase()
        if phase == "hidden":
            return phase, 1, 1, {}
        if phase == "announce":
            return phase, ANNOUNCE_W, ANNOUNCE_H, {}
        buttons = ["discard", "pause", "stop"]
        if self.recorder.has_audio:
            buttons.insert(1, "mic")
        if phase == "timer":
            return phase, timer_width(self._label()), TIMER_H, {}
        width = timer_width(self._label(), buttons=len(buttons))
        y = (TIMER_H + 8 - BAR_BTN) // 2
        spots = {}
        x = width - 8 - BAR_BTN
        for name in reversed(buttons):
            spots[name] = (x, y, x + BAR_BTN, y + BAR_BTN)
            x -= BAR_BTN + 6
        return phase, width, TIMER_H + 8, spots

    def _apply_shape(self, force: bool = False) -> None:
        """Resize to the current phase, keeping the anchored corner still.

        A pill that grew rightwards out of a bottom-right corner would walk
        off the screen; anchoring the CORNER means the announcement, the
        pill and the hovered strip all share an edge, so nothing under the
        pointer moves out from under it when the controls appear.
        """
        phase, width, height, _spots = self._layout()
        if not force and self._shape == (phase, width, height):
            return
        previous = self._shape
        self._shape = (phase, width, height)
        if phase == "hidden":
            self.root.withdraw()
            return
        if self._moved and previous is not None:
            # Hand-placed: keep the same anchored corner where the user put
            # it, so growing still grows away from the nearest edge.
            x, y = self.root.winfo_x(), self.root.winfo_y()
            if self.corner.endswith("right"):
                x += previous[1] - width
            if self.corner.startswith("bottom"):
                y += previous[2] - height
        else:
            x, y = corner_at(self._anchor(), (width, height), self.corner)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.canvas.config(width=width, height=height)
        self.root.update_idletasks()
        radius = CLIP_BAR_RADIUS if phase == "announce" else TIMER_RADIUS
        round_window(self.root, radius)
        self._face(width, height, radius)

    def _face(self, width: int, height: int, radius: int) -> None:
        from PIL import ImageTk
        self._keep["face"] = ImageTk.PhotoImage(
            _vq._rounded_pil(width, height, radius, CARD, PANE, STROKE),
            master=self.root)
        self.canvas.delete("face")
        self.canvas.create_image(0, 0, anchor="nw", image=self._keep["face"],
                                 tags="face")
        self.canvas.tag_lower("face")

    # -- input --

    def _enter(self, _event=None) -> None:
        self._hovering = True

    def _leave(self, _event=None) -> None:
        # NOT collapsed on the spot: resizing the window under the pointer
        # generates its own Leave, and collapsing on that would make the
        # controls flicker out from under the hand that reached for them.
        self._left_at = time.monotonic()

    def _press(self, event) -> None:
        _phase, _w, _h, spots = self._layout()
        name = hit(spots, event.x, event.y)
        if name == "stop":
            self.done.set()
            if self.on_stop is not None:
                self.on_stop()
            return
        if name == "discard":
            self.recorder.discard = True
            if self.on_discard is not None:
                self.on_discard()
            self.done.set()
            return
        if name == "pause":
            self.recorder.toggle_pause()
            return
        if name == "mic":
            if self.on_mic is not None:
                self.on_mic()
            return
        self._drag = (event.x_root - self.root.winfo_x(),
                      event.y_root - self.root.winfo_y())

    def _move(self, event) -> None:
        if self._drag is None:
            return
        dx, dy = self._drag
        self._moved = True
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _release(self, _event=None) -> None:
        self._drag = None

    # -- paint --

    def _paint(self) -> None:
        if self._hovering and time.monotonic() - self._left_at > 0.28:
            if not self._pointer_inside():
                self._hovering = False
        self._apply_shape()
        phase, width, height, spots = self._layout()
        if phase == "hidden":
            return
        if phase == "announce":
            return self._paint_announce(width, height)
        self._paint_timer(width, height, spots)

    def _pointer_inside(self) -> bool:
        try:
            x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
            wx, wy = self.root.winfo_x(), self.root.winfo_y()
            return (wx <= x <= wx + self.root.winfo_width()
                    and wy <= y <= wy + self.root.winfo_height())
        except Exception:
            return False

    def _dot(self, x: int, y: int, size: int = 12) -> None:
        """The red dot, blinking while it records and steady while paused.

        A blink answers "is this still capturing?" from the corner of an
        eye, which is the only question anyone asks an indicator, and it
        answers it without a word to read.
        """
        from PIL import ImageTk
        recorder = self.recorder
        lit = recorder.paused or (time.monotonic() * 1.6) % 1.0 < 0.62
        colour = (224, 163, 43) if recorder.paused else (224, 53, 43)
        dot = _vq.rr_layer((size, size), size // 2,
                           colour + (255 if lit else 60,))
        self._keep["dot"] = ImageTk.PhotoImage(dot, master=self.root)
        self.canvas.create_image(x, y, anchor="nw", image=self._keep["dot"],
                                 tags="live")

    def _text(self, key: str, text: str, x: int, y: int, *, pt: float,
              colour, weight: int = 400, width: int = 300) -> None:
        from PIL import ImageTk
        image = _vq.text_pil(text, width, pt=pt, colour=colour, rtl=False,
                             single=True, weight=weight)
        self._keep[key] = ImageTk.PhotoImage(image, master=self.root)
        self.canvas.create_image(x, y, anchor="nw", image=self._keep[key],
                                 tags="live")

    def _paint_announce(self, width: int, height: int) -> None:
        self.canvas.delete("live")
        self._dot(20, height // 2 - 6)
        left, top, right, bottom = self.recorder.box
        detail = f"{right - left} × {bottom - top}"
        if self.recorder.has_audio:
            detail += "   ·   mic on"
        if self.stop_key:
            detail += f"   ·   {self.stop_key} to stop"
        self._text("title", "Recording started", 42, 11, pt=12.0, colour=INK,
                   weight=600, width=width - 56)
        self._text("detail", detail, 42, 32, pt=9.5, colour=INK_FAINT,
                   width=width - 56)

    def _paint_timer(self, width: int, height: int, spots: dict) -> None:
        from PIL import Image, ImageTk
        canvas = self.canvas
        canvas.delete("live")
        recorder = self.recorder
        self._dot(15, height // 2 - 6)
        self._text("time", self._label(), 34, height // 2 - 11, pt=12.5,
                   colour=INK, weight=600, width=timer_width(self._label()))
        for name, (x0, y0, x1, y1) in spots.items():
            live_mic = (name == "mic" and not recorder.muted)
            fill = ((224, 53, 43, 210) if name == "stop"
                    else (86, 156, 245, 170) if live_mic
                    else (255, 255, 255, 22))
            plate = _vq.rr_layer((x1 - x0, y1 - y0), (x1 - x0) // 2, fill,
                                 (255, 255, 255, 46))
            glyph = {"stop": "stop", "pause": "play" if recorder.paused
                     else "pause", "mic": "mic", "discard": "trash"}[name]
            colour = INK if (name != "mic" or live_mic) else INK_FAINT
            plate.alpha_composite(icon(glyph, 15, colour=colour, width=2),
                                  ((x1 - x0 - 15) // 2, (y1 - y0 - 15) // 2))
            flat = Image.new("RGBA", plate.size, _hex(CARD) + (255,))
            flat.alpha_composite(plate)
            self._keep[f"btn{name}"] = ImageTk.PhotoImage(
                flat.convert("RGB"), master=self.root)
            canvas.create_image(x0, y0, anchor="nw",
                                image=self._keep[f"btn{name}"], tags="live")

    def run(self, stop_event: threading.Event) -> None:
        """Pump until the recording stops. Never longer than one tick
        behind whichever of the three ways to stop was used."""
        root = self.root
        try:
            root.update_idletasks()
            root.update()
            _user32.GetAsyncKeyState(0x1B)
            while not (self.done.is_set() or stop_event.is_set()):
                pressed = _user32.GetAsyncKeyState(0x1B)
                if pressed & 0x8000 or pressed & 0x0001:
                    self.done.set()
                    if self.on_stop is not None:
                        self.on_stop()
                    break
                if self.recorder.stopping:
                    break
                self._paint()
                try:
                    root.update()
                except self.tk.TclError:
                    break
                time.sleep(0.05)         # a clock, not an animation
        finally:
            self._keep.clear()
            for window in (self._frame, root):
                try:
                    if window is not None:
                        window.destroy()
                except Exception:
                    pass
            gc.collect()


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------- the toast

class Toast:
    """"Saved · clip ... · 0:14 · 3.1 MB", with somewhere to click.

    A recording that ends with nothing on screen is a recording you have
    to go and look for. This is the same card stock as the clip bar, in
    the same place, so the thing that was a timer a second ago is now the
    receipt — and it goes away by itself.
    """

    def __init__(self, path: Path, subtitle: str,
                 near: tuple[int, int, int, int], corner: str = "off"):
        import tkinter as tk
        self.tk = tk
        self.path = Path(path)
        self.subtitle = subtitle
        self.near = near
        # The same corner the clock was in, when there was one. A receipt
        # that appears somewhere else is a receipt you have to find; this
        # one takes the place the eye is already watching.
        self.corner = corner
        self.root = tk.Tk()
        self.done = threading.Event()
        self._keep: dict = {}
        self._build()

    def _build(self) -> None:
        from PIL import ImageTk
        width, height = 380, 64
        left, top, right, bottom = self.near
        if self.corner in CORNERS and self.corner != "off":
            x, y = corner_at(work_area_near((left + right) // 2,
                                            (top + bottom) // 2),
                             (width, height), self.corner)
        else:
            screen = monitor_near((left + right) // 2, bottom)
            x, y = plan_bar(self.near, (width, height), screen, gap=12)
        root = self.root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.configure(bg=CARD)
        canvas = self.tk.Canvas(root, width=width, height=height, bg=CARD,
                                highlightthickness=0)
        canvas.pack()
        self.canvas = canvas
        self.size = (width, height)
        self._keep["face"] = ImageTk.PhotoImage(
            _vq._rounded_pil(width, height, CLIP_BAR_RADIUS, CARD, PANE,
                             STROKE), master=root)
        canvas.create_image(0, 0, anchor="nw", image=self._keep["face"])
        root.update_idletasks()
        round_window(root, CLIP_BAR_RADIUS)
        canvas.bind("<ButtonPress-1>", self._press)
        self._paint()

    def _spots(self) -> dict:
        size = 30
        y = (self.size[1] - size) // 2
        x = self.size[0] - 12 - size
        spots = {"close": (x, y, x + size, y + size)}
        x -= size + 6
        spots["folder"] = (x, y, x + size, y + size)
        x -= size + 6
        spots["copy"] = (x, y, x + size, y + size)
        return spots

    def _press(self, event) -> None:
        name = hit(self._spots(), event.x, event.y)
        if name == "close":
            return self.done.set()
        if name == "folder":
            open_folder(self.path)
            return self.done.set()
        if name == "copy":
            copy_file(self.path)
            return self.done.set()
        open_folder(self.path)
        self.done.set()

    def _paint(self) -> None:
        from PIL import Image, ImageTk
        canvas = self.canvas
        canvas.delete("live")
        title = _vq.text_pil(self.path.name, 220, pt=11.5, colour=INK,
                             rtl=False, single=True, weight=600)
        under = _vq.text_pil(self.subtitle, 220, pt=9.5, colour=INK_FAINT,
                             rtl=False, single=True)
        self._keep["title"] = ImageTk.PhotoImage(title, master=self.root)
        self._keep["under"] = ImageTk.PhotoImage(under, master=self.root)
        canvas.create_image(16, 13, anchor="nw", image=self._keep["title"],
                            tags="live")
        canvas.create_image(16, 36, anchor="nw", image=self._keep["under"],
                            tags="live")
        for name, (x0, y0, x1, y1) in self._spots().items():
            plate = _vq.rr_layer((x1 - x0, y1 - y0), (x1 - x0) // 2,
                                 (255, 255, 255, 22), (255, 255, 255, 46))
            plate.alpha_composite(
                icon({"close": "close", "folder": "folder",
                      "copy": "copy"}[name], 15, colour=INK, width=2),
                ((x1 - x0 - 15) // 2, (y1 - y0 - 15) // 2))
            flat = Image.new("RGBA", plate.size, _hex(CARD) + (255,))
            flat.alpha_composite(plate)
            self._keep[name] = ImageTk.PhotoImage(flat.convert("RGB"),
                                                  master=self.root)
            canvas.create_image(x0, y0, anchor="nw", image=self._keep[name],
                                tags="live")

    def run(self, ms: int = TOAST_MS) -> None:
        root = self.root
        until = time.monotonic() + ms / 1000.0
        try:
            root.update_idletasks()
            root.update()
            while not self.done.is_set() and time.monotonic() < until:
                try:
                    root.update()
                except self.tk.TclError:
                    break
                time.sleep(0.04)
        finally:
            self._keep.clear()
            try:
                root.destroy()
            except Exception:
                pass
            gc.collect()


# ------------------------------------------------------------- controller

class ShotToast:
    """The corner card a capture leaves behind instead of an editor.

    THE EDITOR USED TO OPEN EVERY TIME, over the whole screen, for a
    picture that nine times out of ten was going straight into a chat
    window. That is a modal dialog wearing a nicer coat: it interrupts,
    it has to be dismissed, and it makes the common case pay for the rare
    one. So the common case is now silent — the picture is on the
    clipboard before the mouse comes up — and the rare one is a small card
    in a corner for five seconds with the editor one click away.

    It is the shape macOS uses for the same reason, and CleanShot X after
    it: a thumbnail where you can see WHAT was taken, so you know whether
    you need to do anything about it without opening anything.

    THE COUNTDOWN PAUSES UNDER THE POINTER. A card that vanishes while
    the hand is reaching for it is worse than no card, and five seconds is
    not long when the thing you are deciding is "did that capture the bit
    I meant".

    Card stock, not glass, and this one has no choice about it: the screen
    behind it is live again by the time it appears, so there is nothing
    frozen to photograph and blur. Same reasoning as the clip bar.
    """

    def __init__(self, image, box: tuple[int, int, int, int], *,
                 saved: Path | None = None, corner: str = "bottom-right",
                 seconds: int = 5, copied: bool = True,
                 in_shots: bool = True, master=None, owned=()):
        import tkinter as tk
        self.tk = tk
        self.image = image
        self.box = box
        self.saved = saved
        self.corner = corner if corner in CORNERS else "bottom-right"
        self.seconds = max(1, int(seconds))
        self.copied = copied
        # MAY THE NEXT SCREENSHOT SEE THIS CARD? The owner asked for yes
        # (2026-09-04): a card you cannot photograph is a card you cannot
        # show anybody, and the first thing he wanted to do with the new
        # stack was take a picture of it. See _build for the flag this
        # turns off and capture.py's camera card for the same argument
        # reached independently.
        self.in_shots = bool(in_shots)
        self.action: str | None = None
        # ONE ROOT PER PROCESS, N CARDS ON IT. With `master` given this is
        # a Toplevel of the deck's hidden root, which is what lets a dead
        # card's cyclic widget tree be collected by ANY thread later on
        # without Tcl_DeleteInterp ever running: the interpreter belongs
        # to the root, and the root outlives every card. Everything below
        # — withdraw, overrideredirect, -topmost, geometry, the Canvas,
        # the PhotoImages, no_activate, round_window, deiconify — is
        # identical on a Tk and on a Toplevel.
        #
        # `master=None` is still a whole, standalone card that owns its
        # own interpreter, and it is not dead code: it is the fallback
        # Controller._offer takes when the deck cannot start, and it is
        # what the focus test constructs.
        self.root = tk.Tk() if master is None else tk.Toplevel(master)
        self.done = threading.Event()
        self._keep: dict = {}
        self._hover: str | None = None
        self._inside = False
        self._left_at = 0.0
        self._build(tuple(owned))

    # -- construction --

    def _build(self, owned: tuple = ()) -> None:
        from PIL import ImageTk
        # Read BEFORE anything Tk touches: by the time the window exists,
        # the answer is this window. See give_focus_back.
        self._had_focus = _user32.GetForegroundWindow()
        # A CARD MAY ALREADY BE IN FRONT. With a stack, "what had the
        # keyboard" can be the previous card's own window, and handing it
        # "back" would make the stack take the keyboard no_activate exists
        # to leave alone. `owned` is every HWND this stack owns; 0 makes
        # give_focus_back a no-op, which is right — the first card already
        # gave the foreground back and nothing has taken it since.
        if self._had_focus in owned:
            self._had_focus = 0
        width, height = TOAST_W, TOAST_H
        left, top, right, bottom = self.box
        anchor = work_area_near((left + right) // 2, (top + bottom) // 2)
        x, y = corner_at(anchor, (width, height), self.corner)
        root = self.root
        # Built HIDDEN and shown at the end: WS_EX_NOACTIVATE has to be on
        # the window before it is first mapped, or it takes the keyboard
        # once on the way up and the flag only stops it happening again.
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.configure(bg=CARD)
        canvas = self.tk.Canvas(root, width=width, height=height, bg=CARD,
                               highlightthickness=0, cursor="hand2")
        canvas.pack()
        self.canvas = canvas
        self.size = (width, height)
        self._face_img = _vq._rounded_pil(width, height, CLIP_BAR_RADIUS,
                                          CARD, PANE, STROKE)
        self._face_key: tuple | None = None
        self._keep["face"] = ImageTk.PhotoImage(self._face_img, master=root)
        canvas.create_image(0, 0, anchor="nw", image=self._keep["face"])
        root.update_idletasks()
        no_activate(root)
        # THE OWNER WANTS TO BE ABLE TO PHOTOGRAPH HIS OWN CARDS, and
        # that is why this is a switch and not the flat rule the clip bar
        # follows. WDA_EXCLUDEFROMCAPTURE is absolute: a window carrying
        # it is invisible to EVERY grab, including the owner's own, so it
        # cannot be shown to anyone — not in a bug report, not over a
        # call. The camera card refuses the flag for exactly this reason
        # and says so in its own docstring; this is the same argument
        # reached from the other end.
        #
        # The cost, stated plainly because it is real: with `in_shots` on
        # (the default), a screenshot of that corner has the cards in it.
        # What stops the stack turning into a hall of mirrors is not this
        # flag but the ORDER in `_shot_flow` — the desktop is frozen
        # first and the deck is hushed immediately after, so a card is in
        # the picture at most once and never eats the drag.
        if not self.in_shots:
            hide_from_capture(root)
        round_window(root, CLIP_BAR_RADIUS)
        root.deiconify()
        root.update_idletasks()
        give_focus_back(self._had_focus)
        canvas.bind("<ButtonPress-1>", self._press)
        canvas.bind("<Motion>", self._move)
        canvas.bind("<Enter>", self._enter)
        canvas.bind("<Leave>", self._leave)
        self._left = float(self.seconds)
        self._paint()

    # -- layout --

    def _spots(self) -> dict:
        """name -> box. One table for the painter and the hit test, the
        same as every other row of controls in this file."""
        spots: dict[str, tuple[int, int, int, int]] = {}
        x, y, size = TOAST_TEXT_X, TOAST_H - 34, 28
        for name in self._buttons():
            spots[name] = (x, y, x + size, y + size)
            x += size + 6
        # The thumbnail is a button too, and the biggest one: clicking the
        # picture to work on the picture needs no label.
        spots["edit_thumb"] = (12, 12, 12 + TOAST_THUMB[0],
                               12 + TOAST_THUMB[1])
        return spots

    def _buttons(self) -> tuple[str, ...]:
        if self.saved is None:
            return ("edit", "save", "copy", "close")
        return ("edit", "folder", "copy", "close")

    # -- input --

    def _press(self, event) -> None:
        name = hit(self._spots(), event.x, event.y)
        if name == "edit_thumb":
            name = "edit"
        if name is None:
            name = "edit"          # anywhere else on the card means "open it"
        if name == "close":
            self.action = None
        elif name == "folder":
            open_folder(self.saved)
            self.action = None
        elif name == "copy":
            # A thread, for the reason the editor's copy button uses one:
            # this runs on the toast's own Tk pump. And the toast is about
            # to close, so it cannot wait for the answer anyway.
            threading.Thread(target=copy_image, args=(self.image,),
                             daemon=True, name="capture-copy").start()
            self.action = None
        else:
            self.action = name     # "edit" or "save", answered by the caller
        self.done.set()

    def _move(self, event) -> None:
        name = hit(self._spots(), event.x, event.y)
        if name == "edit_thumb":
            name = None
        if name != self._hover:
            self._hover = name

    def _enter(self, _event=None) -> None:
        self._inside = True

    def _leave(self, _event=None) -> None:
        # Not on the spot: a repaint under the pointer generates its own
        # Leave, and collapsing on that would restart the clock in the
        # middle of a reach. Same guard the clip bar keeps.
        self._left_at = time.monotonic()

    def _pointer_inside(self) -> bool:
        try:
            x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
            wx, wy = self.root.winfo_x(), self.root.winfo_y()
            return (wx <= x <= wx + self.size[0]
                    and wy <= y <= wy + self.size[1])
        except Exception:
            return False

    # -- painting --

    def _thumb(self):
        """The capture, letterboxed into the tile. Built once."""
        from PIL import Image
        if "thumb" not in self._keep:
            width, height = TOAST_THUMB
            shrunk = self.image.convert("RGB").copy()
            shrunk.thumbnail((width - 2, height - 2), Image.LANCZOS)
            tile = Image.new("RGB", (width, height), _hex(PANE))
            tile.paste(shrunk, ((width - shrunk.width) // 2,
                                (height - shrunk.height) // 2))
            self._keep["thumb_img"] = tile
        return self._keep["thumb_img"]

    def _paint(self) -> None:
        """Only the clock moves, so only the clock is repainted.

        Everything else — the thumbnail, both lines, all four buttons — is
        composed into ONE picture and swapped when the state it depends on
        changes, which is the pointer moving onto a button and nothing
        else. Before this split the card redrew all of it twenty times a
        second for five seconds after every capture: 4.1 ms a frame, 9% of
        a core, to produce the same pixels. It is the same signature trick
        the camera card's control strip uses, for the same reason.
        """
        from PIL import ImageTk
        key = (self._hover, self.saved is not None)
        if key != self._face_key:
            self._face_key = key
            self._keep["body"] = ImageTk.PhotoImage(self._body(),
                                                    master=self.root)
            self.canvas.delete("body")
            self.canvas.create_image(0, 0, anchor="nw",
                                     image=self._keep["body"], tags="body")
        self.canvas.delete("live")
        self._paint_clock()

    def _body(self):
        """The whole card except the clock, as one picture."""
        from PIL import Image
        card = self._face_img.convert("RGBA")
        card.alpha_composite(self._thumb().convert("RGBA"), (12, 12))

        left, top, right, bottom = self.box
        head = "Copied" if self.copied else "Captured"
        detail = f"{right - left} × {bottom - top}"
        detail += (f"   ·   {self.saved.name}" if self.saved is not None
                   else "   ·   not saved")
        card.alpha_composite(self._line(head, 11.5, INK, weight=600),
                             (TOAST_TEXT_X, 14))
        card.alpha_composite(self._line(detail, 9.0, INK_FAINT),
                             (TOAST_TEXT_X, 34))

        glyphs = {"edit": "pencil", "save": "save", "copy": "copy",
                  "folder": "folder", "close": "close"}
        spots = self._spots()
        for name in self._buttons():
            x0, y0, x1, y1 = spots[name]
            hot = (name == self._hover)
            plate = _vq.rr_layer(
                (x1 - x0, y1 - y0), (x1 - x0) // 2,
                (110, 160, 235, 120) if hot else (255, 255, 255, 22),
                (150, 195, 255, 200) if hot else (255, 255, 255, 46))
            plate.alpha_composite(
                icon(glyphs[name], 14, colour=INK if hot else INK_DIM,
                     width=2), ((x1 - x0 - 14) // 2, (y1 - y0 - 14) // 2))
            card.alpha_composite(plate, (x0, y0))
        return card.convert("RGB")

    def _paint_clock(self) -> None:
        """A line that drains, so "about to go" is visible rather than a
        surprise — and it stops draining while the pointer is on the card,
        which is the only way a five-second offer is honest."""
        left = self.left()
        span = int(self.size[0] * max(0.0, min(1.0, left / self.seconds)))
        if span <= 0:
            return
        colour = ACCENT if not self._inside else FAINT
        self.canvas.create_rectangle(0, self.size[1] - 3, span,
                                     self.size[1], fill=colour, outline="",
                                     tags="live")

    def left(self) -> float:
        """Seconds still on the clock. Frozen while the pointer is on it."""
        return self._left

    def _line(self, text: str, pt: float, colour, weight: int = 400):
        """One line of text as an RGBA layer, ready to composite."""
        return _vq.text_pil(text, self.size[0] - TOAST_TEXT_X - 10, pt=pt,
                            colour=colour, rtl=False, single=True,
                            weight=weight)

    # -- the pump --

    def run(self) -> str | None:
        """Show it until it is clicked or its five seconds are up.

        Returns "edit", "save", or None. The buttons that finish on their
        own — copy again, open the folder, close — answer None too: they
        did the whole of what they promised here.
        """
        root = self.root
        try:
            root.update_idletasks()
            root.update()
            last = time.monotonic()
            while not self.done.is_set():
                now = time.monotonic()
                elapsed, last = now - last, now
                if self.tick(elapsed):
                    break
                try:
                    root.update()
                except self.tk.TclError:
                    break
                time.sleep(0.05)
        finally:
            self._keep.clear()
            try:
                root.destroy()
            except Exception:
                pass
            gc.collect()
        return self.action

    def tick(self, elapsed: float) -> bool:
        """One frame of one card's clock. True when the clock ran out.

        KEEP THIS METHOD BELOW run(). test_the_cards_clock_pauses_under_the_
        pointer slices capture.py from `    def run(self)` to the end of the
        file and asserts the three lines below are in that slice.

        IT IS ITS OWN METHOD BECAUSE THERE IS MORE THAN ONE CARD NOW. The
        deck's pump owns a single Tk root and calls this once per card per
        frame, so each card keeps its own countdown, its own pause under
        the pointer and its own repaint — and a card standing alone still
        runs the identical code through run(), which is the only way the
        stacked and the standalone paths cannot drift apart.
        """
        now = time.monotonic()
        if self._inside and now - self._left_at > 0.2 \
                and not self._pointer_inside():
            self._inside = False
        if not self._inside:
            # HELD, not restarted, while the pointer is on it: the clock
            # resumes where it stopped, so a card brushed by a passing
            # pointer does not outstay its welcome and a card being read
            # does not vanish halfway through the reach for it.
            self._left -= elapsed
            if self._left <= 0:
                return True
        self._paint()
        return False


# "Stop" on the deck's queue. A sentinel OBJECT rather than None, because
# None is a perfectly good value for half the fields a payload carries and
# a queue that cannot tell them apart is a shutdown that fires by accident.
# The same trick overlay.py's `_DONE` plays, for the same reason.
_DECK_DONE = object()


class ShotCards:
    """The deck the corner cards live in, and the thread that draws it.

    WHAT THIS FIXES IS A DEAD KEY. Until now the card blocked the whole
    capture flow: `_busy` was held across its five seconds, so pressing
    the screenshot key again while a card was up did nothing at all
    except log "the capture overlay is already up". That is the wrong
    answer to the most ordinary thing a person does with a screenshot
    key, which is press it twice — the second half of a conversation, the
    error message and then the stack trace under it. So the key is never
    dead now: press it again and a second card joins the first, with its
    own countdown, and the pair stack OLDEST AT THE TOP, NEWEST AT THE
    BOTTOM in whichever corner `toast_corner` names.

    ONE tk.Tk(), WITHDRAWN, NEVER SHOWN, OWNING N Toplevels, PUMPED BY
    ONE THREAD. That is the whole architecture and it is not a matter of
    taste — it is the only shape that obeys the rule AGENTS.md paid for
    three times: a Tk interpreter must be COLLECTED by the thread that
    built it, and `destroy()` does not do that, because a widget tree is
    cyclic and only the generational collector ever frees one, on
    whichever thread happens to trip the allocation threshold. With one
    root held for the life of the process by the thread that made it, a
    dead card's cycle can be collected by anybody at any time and
    `Tcl_DeleteInterp` still never runs. N roots on N threads would
    reopen that abort once per card.

    It generalises `ClipBar` (one root, a sibling Toplevel, one pump, one
    joint burial) wearing `overlay.ReviewCard`'s clothes (a long-lived
    thread, a withdrawn root, a queue in, a `root.after` pump, and a
    per-item deadline that pauses under the pointer).

    THE STACK HOLDS STILL WHILE YOUR HAND IS ON IT. Re-flowing the column
    under the pointer would move the button being reached for, which is
    the same broken promise as a card that vanishes mid-reach — so while
    the pointer is inside any card nothing is re-laid-out and a new
    arrival waits in the queue with its clock not yet started. Released
    on pointer-leave, or after 20 s, whichever comes first.
    """

    # How long the layout may be frozen by a pointer resting on a card
    # before it is released anyway. A hand left on the desk over the
    # corner would otherwise hold the queue for as long as it stayed
    # there, and a capture that never appears is a capture that looks
    # lost — even though the clipboard has had it all along.
    HOLD_S = 20.0

    def __init__(self, cfg_provider, on_action=None):
        self._cfg_of = cfg_provider        # () -> the [capture] section
        self._on_action = on_action        # (action, payload) -> None
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._alive = threading.Event()
        self._closing = threading.Event()
        self._hushed = threading.Event()
        self._settled = threading.Event()  # cards are down: hush() may return
        self._count = 0                    # read from other threads

    # -- the caller's thread --

    @property
    def count(self) -> int:
        """How many cards are up. A plain int, written by the pump and
        read by anybody: nothing here is a Tk object, so it crosses."""
        return self._count

    def start(self) -> bool:
        """Build the deck's thread. False if Tk is not available at all.

        Nothing Tk happens here — the root is built by the thread that
        will own it, which is the entire point.
        """
        if self._thread is not None:
            return True
        try:
            import tkinter  # noqa: F401
        except Exception as e:
            log.info("no corner cards this run: %r", e)
            return False
        self._closing.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="capture-cards")
        self._thread.start()
        if not self._alive.wait(timeout=3):
            log.info("the corner-card deck did not come up in three "
                     "seconds — falling back to a single card")
            self._thread = None
            return False
        return True

    def add(self, image, box, *, saved=None, corner="bottom-right",
            seconds=5, copied=True, in_shots=True, full=None,
            on_action=None) -> None:
        """Offer one capture. Called from OTHER THREADS.

        PLAIN DATA ONLY over this queue: a PIL image, a rectangle, a
        path, three settings, the frozen desktop and a callable. Not one
        Tk object crosses, because a Tk object touched off its own thread
        is the abort with no traceback that AGENTS.md is mostly about.
        """
        if self._thread is None:
            raise CaptureError("the corner-card deck was never started")
        payload = {"image": image, "box": box, "saved": saved,
                   "corner": corner, "seconds": seconds, "copied": copied,
                   "in_shots": in_shots, "full": full,
                   "on_action": on_action or self._on_action}
        self._q.put(payload)
        if full is not None:
            # THE TRADE, IN NUMBERS, so it is falsifiable rather than a
            # feeling. Each card holds the whole desktop frozen at the
            # moment it was taken, which is what lets its editor open on
            # the pixels as they WERE — and on this desk that is ~18 MB
            # a card. If this line ever reads like a memory leak, lower
            # `toast_stack`; it is the dial for exactly this.
            n = self._count + self._q.qsize()
            log.debug("capture cards: %d up, holding %.0f MiB of frozen "
                      "screen", n, n * full.width * full.height * 3
                      / (1 << 20))

    def hush(self, timeout: float = 0.25) -> None:
        """Take every card off the screen and stop every clock.

        A full-screen capture window is about to map, and topmost cards
        in a corner would eat the drag over that corner — the
        bottom-right is where the taskbar clock is and where people drag
        TO. So the deck goes dark for the length of the selection and
        comes back with the same seconds left it had, because none of
        them were spent on a screen nobody could see.

        THIS USED TO BE ABOUT THE PICTURE TOO, and it no longer is. The
        screenshot flow now freezes the desktop BEFORE it calls this, on
        purpose, so the cards are in the picture the owner is about to
        take a crop of — that was the ask, 2026-09-04. Being off the live
        screen for the drag and being absent from the freeze are two
        different things, and only the first one was ever worth having.

        Waits briefly so the cards are actually gone before the selector
        maps — but ONLY WHEN THERE IS SOMETHING TO WAIT FOR. This is
        called from `begin_shot`, which main.py runs inside the OS
        keyboard hook, and hotkey.py's budget there is 300 ms: exceed it
        and Windows silently unhooks, whose symptom is "my hotkey stopped
        working" with nothing logged anywhere. With no cards up — the
        common case — the flag is set and this returns in microseconds;
        with cards up it is one pump frame, about 50 ms; the quarter of a
        second is the ceiling for a pump that has stopped answering, and
        it is still inside the budget.
        """
        if self._thread is None:
            return
        self._settled.clear()
        self._hushed.set()
        if not self._count:
            return
        self._settled.wait(timeout=timeout)

    def unhush(self) -> None:
        """The screen is the owner's again. Put the cards back."""
        self._hushed.clear()

    def stop(self) -> None:
        """Bury the deck: every card, then the root, then collect — all
        on the thread that built them. The join is bounded because
        shutdown must not hang on a window."""
        if self._thread is None:
            return
        self._q.put(_DECK_DONE)
        self._closing.set()
        self._thread.join(timeout=3)
        self._thread = None

    # -- the deck's own thread --

    def _run(self) -> None:
        try:
            self._build_and_loop()
        except Exception:
            log.exception("the corner-card deck died")
        finally:
            self._alive.clear()
            self._count = 0
            self._settled.set()

    def _build_and_loop(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        cards: list[ShotToast] = []
        state = {"tick": time.monotonic(), "held_at": 0.0, "held": False,
                 "expired": False, "moved": False, "dark": False}
        self._alive.set()

        def owned() -> tuple:
            """Every HWND this deck owns, for the focus guard."""
            out = []
            for card in cards:
                try:
                    out.append(_user32.GetParent(int(card.root.winfo_id()))
                               or int(card.root.winfo_id()))
                    out.append(int(card.root.winfo_id()))
                except Exception:
                    pass
            return tuple(out)

        def bury(card: ShotToast) -> None:
            # ORDER MATTERS AND IT IS THE ORDER ShotToast.run's finally
            # already uses. ImageTk.PhotoImage.__del__ calls back into
            # Tcl; freed on a foreign thread it raises inside __del__ and
            # leaks a Tcl image, so the pictures are dropped first, here,
            # by the thread that made them, and the window second.
            try:
                card._keep.clear()
            except Exception:
                pass
            try:
                card.root.destroy()
            except Exception:
                pass

        def limit(card: ShotToast) -> int:
            """The live ceiling: the owner's number, capped by the screen.

            Read fresh every time, like every other config value in this
            module — the dashboard writes `toast_stack` while the app is
            running and the next capture should honour it.
            """
            try:
                wanted = int(getattr(self._cfg_of(), "toast_stack", 4))
            except Exception:
                wanted = 4
            return max(1, min(wanted, stack_fits(self._anchor(card),
                                                 (TOAST_W, TOAST_H))))

        def relay() -> None:
            """Put every card where the stack says it belongs.

            Only when something CHANGED. Re-issuing the same geometry
            twenty times a second is the mistake `_paint` already
            documents from the other side: the pixels come out identical
            and the CPU does not.
            """
            if not cards or not state["moved"]:
                return
            state["moved"] = False
            places = stack_layout([self._anchor(c) for c in cards],
                                  (TOAST_W, TOAST_H), cards[-1].corner)
            for card, (x, y) in zip(cards, places):
                try:
                    card.root.geometry(f"{TOAST_W}x{TOAST_H}+{x}+{y}")
                except Exception:
                    pass

        def holding() -> bool:
            """Is a hand on the stack? Then nothing moves and nothing new
            arrives — until HOLD_S says otherwise.

            Once the 20 s are up the hold STAYS released until the pointer
            actually leaves, rather than re-arming: a hand resting on the
            corner would otherwise make every later capture wait another
            twenty seconds, one at a time, forever.
            """
            if not any(c._inside for c in cards):
                state["held"] = state["expired"] = False
                return False
            if state["expired"]:
                return False
            now = time.monotonic()
            if not state["held"]:
                state["held"], state["held_at"] = True, now
                return True
            if now - state["held_at"] < self.HOLD_S:
                return True
            log.info("the pointer has been on the capture cards for %.0f s "
                     "— letting the stack move again", self.HOLD_S)
            state["expired"] = True
            return False

        def take(payload: dict) -> None:
            card = ShotToast(payload["image"], payload["box"],
                             saved=payload["saved"],
                             corner=payload["corner"],
                             seconds=payload["seconds"],
                             copied=payload["copied"],
                             in_shots=payload.get("in_shots", True),
                             master=root, owned=owned())
            card.full = payload["full"]
            card.on_action = payload["on_action"]
            cards.append(card)
            ceiling = limit(card)
            while len(cards) > ceiling:
                # OLDEST OUT, and immediately. Nothing is lost: every one
                # of these captures is already on the clipboard, and the
                # ones written to `folder` are already on disk. What goes
                # is the OFFER, and the offer the owner is least likely
                # to still want is the one that has been sitting there
                # longest.
                old = cards.pop(0)
                log.info("capture cards: %d is the most that fit here — "
                         "taking the oldest one down early (its picture is "
                         "still on the clipboard)", ceiling)
                bury(old)
            state["moved"] = True
            relay()
            # FLUSHED IN THE SAME BREATH AS THE MAP. ShotToast._build
            # deiconifies the card at corner_at's single-card position,
            # because that is all a card on its own has ever needed to
            # know; relay() then moves it to its slot. Letting those two
            # be separated by a pump frame would show the new card at the
            # top corner for 20 ms before it dropped into place.
            try:
                root.update_idletasks()
            except Exception:
                pass

        def drain() -> bool:
            """Queue in. False when the sentinel says to shut down."""
            while True:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    return True
                if item is _DECK_DONE:
                    return False
                if self._hushed.is_set() or holding():
                    # BACK ON THE QUEUE, CLOCK NOT STARTED. A card built
                    # behind a selector or under a resting hand would
                    # spend its seconds where nobody could act on it.
                    self._q.put(item)
                    return True
                try:
                    take(item)
                except Exception:
                    log.exception("a capture card could not be built")

        def hush_state() -> bool:
            """Withdraw or restore the whole deck. True while it is dark.

            Only on the EDGE — withdrawing an already-withdrawn window
            twenty times a second is twenty pointless trips through the
            window manager, and deiconify() on the way back is where a
            flicker would come from if it were issued every frame.
            """
            want = self._hushed.is_set()
            if want != state["dark"]:
                state["dark"] = want
                for card in cards:
                    try:
                        if want:
                            card.root.withdraw()
                        else:
                            card.root.deiconify()
                    except Exception:
                        log.debug("a capture card would not hide",
                                  exc_info=True)
                state["moved"] = True
            if want:
                self._settled.set()
            return want

        def pump() -> None:
            if not drain():
                self._closing.set()
                return
            now = time.monotonic()
            elapsed, state["tick"] = now - state["tick"], now
            if hush_state():
                # FROZEN, NOT SPENT: no clock is touched while the cards
                # are off the screen, so each one comes back with exactly
                # the seconds it had. A card must not run out behind a
                # full-screen selector nobody could have clicked it from.
                self._count = len(cards)
                root.after(50, pump)
                return
            spent = []
            for card in cards:
                try:
                    if card.done.is_set() or card.tick(elapsed):
                        spent.append(card)
                except Exception:
                    log.debug("a capture card stopped painting",
                              exc_info=True)
                    spent.append(card)
            for card in spent:
                if card in cards:
                    cards.remove(card)
                self._answer(card)
                bury(card)
                state["moved"] = True
            if not holding():
                relay()
            self._count = len(cards)
            root.after(50, pump)

        pump()
        try:
            self._pump(root)
        finally:
            self._count = 0
            for card in cards:
                bury(card)
            cards.clear()
            try:
                root.destroy()
            except Exception:
                pass
            owned = bury = limit = relay = None            # noqa: F841
            holding = take = drain = hush_state = pump = None   # noqa: F841
            root = None                                    # noqa: F841
            gc.collect()

    def _pump(self, root) -> None:
        """update() in a loop, never mainloop().

        overlay.py's module docstring has the reproduction: `quitMainLoop`
        is a MODULE-LEVEL global in _tkinter, so one interpreter's quit()
        can end another interpreter's loop. With a status dot and a splash
        alive at once it was a coin toss which loop died. update() touches
        nothing shared.
        """
        while not self._closing.is_set():
            try:
                root.update()
            except Exception:
                return
            time.sleep(0.02)

    @staticmethod
    def _anchor(card: "ShotToast") -> tuple[int, int, int, int]:
        """The WORK area a card belongs to — the monitor its capture was
        taken on, which is why two screens make two columns."""
        left, top, right, bottom = card.box
        return work_area_near((left + right) // 2, (top + bottom) // 2)

    def _answer(self, card: "ShotToast") -> None:
        """Hand a finished card's verdict back to whoever offered it.

        THE HANDLER MUST RETURN AT ONCE and it is the caller's job to see
        that it does — "edit" opens a full-screen editor with an
        interpreter of its own, and doing that here would stop every
        other card's clock for as long as the editor stayed open, on the
        one thread that is allowed to touch them. Controller._offer's
        handler spawns `capture-card-action` and returns; this end only
        packs the plain data and logs if the hand-off throws.
        """
        action, handler = card.action, getattr(card, "on_action", None)
        if action is None or handler is None:
            return
        payload = {"action": action, "image": card.image, "box": card.box,
                   "saved": card.saved, "full": getattr(card, "full", None)}
        try:
            handler(payload)
        except Exception:
            log.exception("the capture card's %s could not be started",
                          action)


# ------------------------------------------------------------ the camera

class CameraWindow:
    """The live picture, and one button that turns it into a file.

    A card in the middle of the monitor you are on: the camera above, a
    row of controls below, and a shutter in the middle of the row because
    that is where a hand looks for one. Space or Enter is the same button;
    **T** cycles the self-timer, **M** flips the picture, **C** moves to
    the next camera, **Esc** closes without taking anything.

    IT KEEPS THE SAME PROMISE THE SCREENSHOT KEY KEEPS. The moment the
    shutter fires the picture is on the clipboard and in `captures\\`, and
    everything after that — the flash, the editor, the drawing — is an
    offer. Closing the editor with Esc loses nothing, because nothing was
    waiting to be saved.

    NOT GLASS, for the clip bar's reason: the glass in this app is painted
    from a photograph of what is behind the window, and behind this one is
    a live desktop. Card stock with SetWindowRgn corners, and the picture
    inside it is a plain inset rectangle — a rounded mask over the preview
    would be a mask recomputed twenty-five times a second for four corner
    pixels.

    ONE PhotoImage FOR THE WHOLE SESSION. `PhotoImage.paste()` overwrites
    the pixels of an existing Tk image; building a new one per frame
    allocates a 1280x720 bitmap twenty-five times a second and hands the
    old one to the garbage collector, on a thread that owns a Tcl
    interpreter (AGENTS.md explains why that is worse than it sounds).
    """

    def __init__(self, camera: Camera, *, names=(), open_camera=None,
                 folder: str = "captures", copy: bool = True,
                 edit: bool = True, timer: int = 0, hotkey: str = "",
                 on_saved=None):
        import tkinter as tk
        self.tk = tk
        self.camera = camera
        self.names = list(names)
        self.open_camera = open_camera      # name -> Camera, already started
        self.folder = folder
        self.copy = copy
        self.edit = edit
        self.timer = timer if timer in CAM_TIMERS else 0
        self.hotkey = hotkey
        self.on_saved = on_saved

        self.result: dict | None = None
        self.frozen = None                  # the still, once it is taken
        self.saved_path: Path | None = None
        self.backdrop = None                # the desktop, for the editor

        self.preview_size = camera.preview_size
        self.card_w = max(self.preview_size[0] + CAM_PAD * 2, CAM_MIN_W)
        self.card_h = self.preview_size[1] + CAM_PAD + CAM_STRIP_H
        # Centred rather than left at CAM_PAD, so a picture narrower than
        # the control row sits in the middle of it instead of against one
        # edge with a hole beside it.
        self.pad_x = (self.card_w - self.preview_size[0]) // 2
        self.spots = camera_bar(self.card_w, switchable=len(self.names) > 1)

        self._closing = False
        self._armed_at: float | None = None
        self._flash_until = 0.0
        self._done_at = 0.0
        self._status = ""
        self._status_until = 0.0
        self._hover: str | None = None
        self._drag: tuple[int, int] | None = None
        self._keep: dict = {}
        self._photo = None
        self._strip_key: tuple | None = None
        self._count_key: int | None = None
        self._said_wake = False

        self.root = tk.Tk()
        self._build()

    # -- construction --

    def _build(self) -> None:
        root = self.root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=CARD)
        canvas = self.tk.Canvas(root, bg=CARD, highlightthickness=0,
                                width=self.card_w, height=self.card_h,
                                cursor="arrow")
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas

        px, py = root.winfo_pointerx(), root.winfo_pointery()
        left, top, right, bottom = work_area_near(px, py)
        x = left + ((right - left) - self.card_w) // 2
        y = top + int(((bottom - top) - self.card_h) * 0.42)
        root.geometry(f"{self.card_w}x{self.card_h}+{x}+{y}")
        root.update_idletasks()
        round_window(root, CAM_RADIUS)
        self._face()

        # DELIBERATELY NOT hide_from_capture, unlike the clip bar. That
        # flag is there so a recorder's own controls stay out of the
        # recording, which is a real problem for a window that floats over
        # the region being recorded. This window floats over nothing it is
        # recording, and the flag has a cost: an excluded window cannot be
        # screenshotted, shared or recorded BY THE OWNER either — not by
        # this app's own screenshot key, not by Teams, not for a bug
        # report. The desktop behind it is grabbed by withdrawing first
        # (see _freeze_desktop), which costs one repaint at the exact
        # moment the screen is about to be covered by the editor anyway.

        canvas.bind("<ButtonPress-1>", self._press)
        canvas.bind("<B1-Motion>", self._move)
        canvas.bind("<ButtonRelease-1>", self._release)
        canvas.bind("<Motion>", self._hover_at)
        root.bind_all("<KeyPress>", self._on_key)

    def _face(self) -> None:
        from PIL import ImageTk
        self._keep["face"] = ImageTk.PhotoImage(
            _vq._rounded_pil(self.card_w, self.card_h, CAM_RADIUS, CARD,
                             PANE, STROKE), master=self.root)
        self.canvas.delete("face")
        self.canvas.create_image(0, 0, anchor="nw", image=self._keep["face"],
                                 tags="face")
        self.canvas.tag_lower("face")

    # -- what the user does --

    def say(self, text: str, ttl_ms: int = 3200) -> None:
        self._status = text
        self._status_until = time.monotonic() + ttl_ms / 1000.0

    def close(self) -> None:
        self._closing = True

    # The letters, matched by KEYCODE and never by keysym. With a
    # non-Latin layout active Tk reports the physical T as a Hebrew letter
    # — the repo already has a test for that, written when the dashboard's
    # key capture walked into it — and on THIS machine the non-Latin layout
    # is the common case, not the exotic one. Binding the LETTER sequences
    # here was measured doing nothing at all, which is the worst way for a
    # shortcut to fail: silently, and only for the person who needs it.
    _KEYS = {0x20: "shoot", 0x0D: "shoot", 0x54: "timer", 0x4D: "mirror",
             0x43: "switch"}

    def _on_key(self, event) -> None:
        action = self._KEYS.get(getattr(event, "keycode", None))
        if action is None:
            # Whatever Windows numbers differently from Tk — the numpad
            # Enter is the one that matters.
            action = {"space": "shoot", "Return": "shoot",
                      "KP_Enter": "shoot"}.get(getattr(event, "keysym", ""))
        if action == "shoot":
            self.shoot()
        elif action == "timer":
            self._cycle_timer()
        elif action == "mirror":
            self._flip()
        elif action == "switch":
            self._switch()

    def _press(self, event) -> None:
        if self.frozen is not None:
            return
        name = self._spot_at(event.x, event.y)
        if name == "shutter":
            return self.shoot()
        if name == "timer":
            return self._cycle_timer()
        if name == "mirror":
            return self._flip()
        if name == "switch":
            return self._switch()
        if name == "close":
            return self.close()
        # Anywhere else on the card is a handle. A window with no title
        # bar has to be draggable by its face or it cannot be got out of
        # the way of the thing you were about to photograph.
        self._drag = (event.x_root - self.root.winfo_x(),
                      event.y_root - self.root.winfo_y())

    def _move(self, event) -> None:
        if self._drag is None:
            return
        dx, dy = self._drag
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _release(self, _event=None) -> None:
        self._drag = None

    def _hover_at(self, event) -> None:
        name = self._spot_at(event.x, event.y)
        if name != self._hover:
            self._hover = name
            self.canvas.config(cursor="hand2" if name else "arrow")

    def _spot_at(self, x: int, y: int) -> str | None:
        return hit(self.spots, x, y - (self.card_h - CAM_STRIP_H))

    # -- the three switches --

    def _cycle_timer(self) -> None:
        if self._armed_at is not None:
            self._armed_at = None
            return self.say("timer cancelled")
        self.timer = next_in(CAM_TIMERS, self.timer)
        self._strip_key = None
        self.say("no timer" if not self.timer else f"{self.timer} s timer")

    def _flip(self) -> None:
        """Mirror BOTH the preview and the photo, or neither.

        A preview that is mirrored while the file is not is the one bug
        this whole module argues against — see render_shot, and preview_fit
        for the same argument about size. It is off by default because the
        commonest thing anyone holds up to a webcam is something with
        writing on it, and mirrored writing is unreadable.
        """
        self.camera.mirror = not self.camera.mirror
        self._strip_key = None
        self.say("mirrored" if self.camera.mirror else "not mirrored")

    def _switch(self) -> None:
        if len(self.names) < 2 or self.open_camera is None:
            return self.say("there is only one camera")
        name = next_in(self.names, self.camera.name)
        self.say(f"switching to {name}...", ttl_ms=8000)
        self._paint()
        try:
            self.root.update()
        except self.tk.TclError:
            return
        mirror = self.camera.mirror
        self.camera.close()
        try:
            self.camera = self.open_camera(name, mirror)
        except Exception as e:
            log.exception("could not open %r", name)
            return self.say(f"{name} would not open: {e}", ttl_ms=6000)
        self._said_wake = False
        self.say(name)

    # -- the shutter --

    def shoot(self) -> None:
        """Take it now, or arm the timer if one is set."""
        if self.frozen is not None:
            return
        if self._armed_at is not None:
            self._armed_at = None
            self._strip_key = None
            return self.say("timer cancelled")
        if not self.camera.live:
            return self.say("the camera has not woken up yet")
        if self.timer:
            self._armed_at = time.monotonic()
            self._strip_key = None
            return self.say(f"{self.timer} s — esc or the shutter cancels")
        self._fire()

    def _fire(self) -> None:
        """The picture, the file, the clipboard — in that order, at once.

        THE CAMERA IS CLOSED FIRST. Everything after this line is pixels
        we already hold, so there is no reason for the lens to stay open
        through the flash, the save and the editor, and the little light
        beside it is the only thing the owner has to go on.
        """
        image = self.camera.still()
        self._armed_at = None
        self._strip_key = None
        if image is None:
            return self.say("the camera has not woken up yet")
        self.camera.close()
        self.frozen = image
        now = time.monotonic()
        self._flash_until = now + CAM_FLASH_MS / 1000.0
        try:
            self.saved_path = save_image(image, self.folder, kind="photo")
        except Exception as e:
            log.exception("could not save the photo")
            self.say(f"could not save: {e}", ttl_ms=6000)
            self._done_at = now + 2.5
            return
        copied = copy_image(image) if self.copy else False
        self.say(f"{'copied · ' if copied else ''}{self.saved_path.name}",
                 ttl_ms=9000)
        log.info("photo %d×%d saved to %s%s", image.width, image.height,
                 self.saved_path, " and copied" if copied else "")
        if self.on_saved is not None:
            self.on_saved(self.saved_path)
        # Long enough to see the picture stop moving, and no longer: with
        # the editor coming it is the flash plus a beat; without it the
        # window has to stay up long enough for the filename to be read.
        dwell = (CAM_FLASH_MS + 220) if self.edit else CAM_HOLD_MS
        self._done_at = now + dwell / 1000.0

    def _freeze_desktop(self):
        """The screen behind this window, for the editor to lay the photo on.

        WITHDRAW, PUMP, THEN GRAB, and the pump is not optional: hiding a
        window only asks Windows to repaint what was underneath, and a
        grab issued in the same breath comes back with the card still in
        it. Three ticks is enough here and it is invisible in practice —
        the screen this blinks is the screen the editor is about to dim
        one frame later.
        """
        from PIL import ImageGrab
        self.root.withdraw()
        for _ in range(3):
            try:
                self.root.update()
            except self.tk.TclError:
                break
            time.sleep(0.02)
        return ImageGrab.grab(all_screens=True).convert("RGB")

    # -- the pump --

    def _tick(self) -> None:
        now = time.monotonic()
        if self.frozen is not None:
            if now >= self._done_at:
                self._finish()
            return
        if self._armed_at is not None:
            if countdown_left(self._armed_at, now, self.timer) <= 0:
                self._fire()
            return
        if self.camera.error:
            self.say(f"{self.camera.name}: {self.camera.error}", ttl_ms=9000)
            return
        if not self.camera.live and not self._said_wake:
            if now - self.camera.opened_at > CAM_WAKE_S:
                self._said_wake = True
                self.say(f"{self.camera.name} did not send a picture in "
                         f"{CAM_WAKE_S:.0f} s — is something else using it?",
                         ttl_ms=9000)

    def _finish(self) -> None:
        if self.edit and self.saved_path is not None:
            self.backdrop = self._freeze_desktop()
        self.result = {"photo": self.frozen, "box": self.preview_rect(),
                       "path": self.saved_path, "backdrop": self.backdrop}
        self.close()

    def preview_rect(self) -> tuple[int, int, int, int]:
        """Where the picture is, in SCREEN pixels — the editor's anchor.

        Public because the log line that says the camera is open says
        WHERE, and "the window opened somewhere I could not see" is the
        report this answers without another run.
        """
        x = self.root.winfo_rootx() + self.pad_x
        y = self.root.winfo_rooty() + CAM_PAD
        return (x, y, x + self.preview_size[0], y + self.preview_size[1])

    def run(self) -> dict | None:
        root = self.root
        try:
            root.update_idletasks()
            root.update()
            # The same foreground grab the selector uses, and without the
            # Alt tap for the same reason: the tap arms the menu bar of
            # whatever is underneath and eats the first click.
            _vq.take_foreground(root, alt_tap=False)
            _user32.GetAsyncKeyState(0x1B)      # prime, discard
            # Seeded from the keyboard, not from False: a stuck Escape
            # would otherwise close this card the instant it opened, with
            # nothing on screen long enough to read. See esc_held.
            held = esc_held()
            if held:
                log.info("esc is held down as the camera opens — it will "
                         "stay up until esc is released and pressed again")
            while not self._closing:
                state = _user32.GetAsyncKeyState(0x1B)
                down, fresh = bool(state & 0x8000), bool(state & 0x0001)
                # ONE PRESS IS ONE PRESS, and this window is the first
                # here that needs to know it. Esc means two things —
                # cancel the countdown, then close — and the pump polls at
                # 66 Hz while a human tap holds the key for eighty
                # milliseconds. Without the latch the first tick cancelled
                # the timer and the third closed the window, so "esc
                # cancels the countdown" was true for about 15 ms.
                # Measured 2026-08-26, on a scripted 60 ms tap.
                if (down or fresh) and not held:
                    if self._armed_at is not None and self.frozen is None:
                        self._armed_at = None
                        self._strip_key = None
                        self.say("timer cancelled")
                    else:
                        break
                held = down
                self._tick()
                self._paint()
                try:
                    root.update()
                except self.tk.TclError:
                    break
                time.sleep(_TICK_S)
        finally:
            self.camera.close()
            self._keep.clear()
            self._photo = None
            try:
                root.destroy()
            except Exception:
                pass
            gc.collect()
        return self.result

    # -- painting --

    def _paint(self) -> None:
        from PIL import ImageTk
        canvas = self.canvas
        image = self.frozen if self.frozen is not None else self.camera.latest
        if image is not None:
            if self._photo is None:
                self._photo = ImageTk.PhotoImage(image, master=self.root)
                canvas.create_image(self.pad_x, CAM_PAD, anchor="nw",
                                    image=self._photo, tags="view")
            else:
                self._photo.paste(image)
        self._paint_strip()
        canvas.delete("over")
        if image is None:
            self._paint_waiting()
        if self._armed_at is not None:
            self._paint_countdown()
        if time.monotonic() < self._flash_until:
            canvas.create_rectangle(
                self.pad_x, CAM_PAD, self.pad_x + self.preview_size[0],
                CAM_PAD + self.preview_size[1], fill="#ffffff", outline="",
                tags="over")
        self._paint_status()

    def _paint_waiting(self) -> None:
        """Before the first frame. Measured 654-829 ms, and a card that is
        a black hole for three quarters of a second is a card that looks
        broken."""
        self.canvas.create_rectangle(
            self.pad_x, CAM_PAD, self.pad_x + self.preview_size[0],
            CAM_PAD + self.preview_size[1], fill=PANE, outline="",
            tags="over")
        self._text("wake", f"waking {self.camera.name}...",
                   self.pad_x + 18,
                   CAM_PAD + self.preview_size[1] // 2 - 12,
                   pt=12.5, colour=INK_DIM,
                   width=self.preview_size[0] - 36)

    def _paint_countdown(self) -> None:
        from PIL import ImageTk
        left = countdown_left(self._armed_at, time.monotonic(), self.timer)
        if left != self._count_key or "count" not in self._keep:
            self._count_key = left
            self._keep["count"] = ImageTk.PhotoImage(
                self._count_plate(left), master=self.root)
        image = self._keep["count"]
        self.canvas.create_image(
            self.pad_x + self.preview_size[0] // 2,
            CAM_PAD + self.preview_size[1] // 2, anchor="center",
            image=image, tags="over")

    def _count_plate(self, left: int):
        """The number, on a disc dark enough to read it over anything."""
        from PIL import Image
        size = 132
        plate = _vq.rr_layer((size, size), size // 2, (8, 16, 32, 168),
                             (255, 255, 255, 40))
        # Trimmed to the ink before it is centred, for the reason the timer
        # chip is: text_pil hands back a picture of the BOX it was given
        # with the glyphs at one end, and centring that box puts a numeral
        # visibly off to the left of the disc it is supposed to be in.
        glyph = _vq.text_pil(str(left), size * 2, pt=54, colour=INK,
                             rtl=False, single=True, weight=700)
        ink = glyph.getbbox()
        if ink is not None:
            glyph = glyph.crop(ink)
        plate.alpha_composite(glyph, ((size - glyph.width) // 2,
                                      (size - glyph.height) // 2))
        flat = Image.new("RGBA", plate.size, (0, 0, 0, 0))
        flat.alpha_composite(plate)
        return flat

    def _paint_status(self) -> None:
        if self._status and time.monotonic() > self._status_until:
            self._status = ""
        text = self._status or self._hint()
        if not text:
            return
        self._text("status", text, self.pad_x + 10,
                   CAM_PAD + self.preview_size[1] - 26, pt=10.0,
                   colour=INK_DIM, width=self.preview_size[0] - 20,
                   shade=True)

    def _hint(self) -> str:
        if self.frozen is not None:
            return ""
        parts = ["space to take it"]
        if self.timer:
            parts.append(f"t: {self.timer} s")
        else:
            parts.append("t: timer")
        parts.append("m: mirror")
        if len(self.names) > 1:
            parts.append("c: next camera")
        parts.append("esc closes")
        return "   ·   ".join(parts)

    def _text(self, key: str, text: str, x: int, y: int, *, pt: float,
              colour, width: int = 300, weight: int = 400,
              shade: bool = False) -> None:
        """One line of text over the picture.

        `shade` puts it on a dark plate. Over a live camera there is no
        telling what is behind a caption — a white wall makes pale text
        vanish — and the alternative (a black outline per glyph) is four
        more GDI passes per tick.
        """
        from PIL import Image, ImageTk
        cached = self._keep.get(f"{key}:key")
        if cached != (text, colour, shade):
            glyph = _vq.text_pil(text, width, pt=pt, colour=colour, rtl=False,
                                 single=True, weight=weight)
            if shade:
                pad = 7
                plate = _vq.rr_layer(
                    (glyph.width + pad * 2, glyph.height + pad), 9,
                    (8, 16, 32, 150))
                plate.alpha_composite(glyph, (pad, pad // 2))
                glyph = plate
            flat = Image.new("RGBA", glyph.size, (0, 0, 0, 0))
            flat.alpha_composite(glyph)
            self._keep[key] = ImageTk.PhotoImage(flat, master=self.root)
            self._keep[f"{key}:key"] = (text, colour, shade)
        self.canvas.create_image(x, y, anchor="nw", image=self._keep[key],
                                 tags="over")

    def _paint_strip(self) -> None:
        """The control row, composed once per STATE and not per frame.

        Nothing on it changes at twenty-five frames a second — the chips
        answer to the timer, the mirror and the pointer — so it is
        rebuilt on a signature of those three and pasted otherwise. The
        preview above it is the only thing that has to be new every tick.
        """
        from PIL import ImageTk
        armed = self._armed_at is not None
        key = (self.timer, self.camera.mirror, self._hover, armed,
               self.frozen is not None)
        if key != self._strip_key or "strip" not in self._keep:
            self._strip_key = key
            self._keep["strip"] = ImageTk.PhotoImage(
                self._strip_image(armed), master=self.root)
            self.canvas.delete("strip")
            self.canvas.create_image(0, self.card_h - CAM_STRIP_H,
                                     anchor="nw", image=self._keep["strip"],
                                     tags="strip")

    def _strip_image(self, armed: bool):
        from PIL import Image
        plate = Image.new("RGBA", (self.card_w, CAM_STRIP_H),
                          _hex(CARD) + (255,))
        for name, (x0, y0, x1, y1) in self.spots.items():
            if name == "shutter":
                continue
            lit = ((name == "mirror" and self.camera.mirror)
                   or (name == "timer" and bool(self.timer)))
            fill = ((86, 156, 245, 170) if lit
                    else (255, 255, 255, 40) if self._hover == name
                    else (255, 255, 255, 20))
            chip = _vq.rr_layer((x1 - x0, y1 - y0), (x1 - x0) // 2, fill,
                                (255, 255, 255, 46))
            colour = INK if (lit or self._hover == name) else INK_FAINT
            if name == "timer" and self.timer:
                # The NUMBER instead of the stopwatch once one is set: a
                # chip that is merely lit says a timer is on and not which,
                # and 3 s and 10 s are different plans.
                #
                # Laid out in a WIDE box and then trimmed to its ink.
                # text_pil returns a picture of the box it was given, with
                # the glyphs at one end of it, so centring on the returned
                # size put the numeral against the chip's left curve and
                # clipped it — seen in the first live screenshot, which is
                # the only place it could have been seen.
                mark = _vq.text_pil(str(self.timer), 96, pt=12.0,
                                    colour=colour, rtl=False, single=True,
                                    weight=700)
                ink = mark.getbbox()
                if ink is not None:
                    mark = mark.crop(ink)
            else:
                mark = icon({"mirror": "mirror", "timer": "timer",
                             "switch": "switch", "close": "close"}[name],
                            16, colour=colour, width=2)
            chip.alpha_composite(mark, ((x1 - x0 - mark.width) // 2,
                                        (y1 - y0 - mark.height) // 2))
            plate.alpha_composite(chip, (x0, y0))
        plate.alpha_composite(self._shutter_image(armed),
                              self.spots["shutter"][:2])
        return plate.convert("RGB")

    def _shutter_image(self, armed: bool):
        """A ring with a disc in it — the shape every camera has had since
        cameras had buttons, and the one control here that needs no label.

        Red while a timer is counting, because then the button means
        CANCEL and a button that means two things has to look like two
        things.
        """
        ring = _vq.rr_layer((SHUTTER, SHUTTER), SHUTTER // 2, (0, 0, 0, 0),
                            (238, 245, 255, 225), 2)
        inner = SHUTTER - 14
        if armed:
            fill = (224, 53, 43, 245)
        elif self.frozen is not None:
            fill = (238, 245, 255, 90)
        elif self._hover == "shutter":
            fill = (255, 255, 255, 255)
        else:
            fill = (238, 245, 255, 226)
        disc = _vq.rr_layer((inner, inner), inner // 2, fill)
        ring.alpha_composite(disc, ((SHUTTER - inner) // 2,
                                    (SHUTTER - inner) // 2))
        return ring


def _pointer() -> tuple[int, int]:
    """Where the mouse is, without a Tk window to ask.

    The camera window has to know which monitor it is opening on BEFORE it
    exists, because the size of the picture depends on the work area it
    has to fit into (preview_fit).
    """
    point = w.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


class Controller:
    """What main.py holds: three hotkeys land here.

    Constructing one is cheap and imports nothing heavy — Pillow, Tk, PyAV
    and sounddevice all load on the first press, so an owner who never
    presses either key pays nothing for the idea of them.

    ONE THING AT A TIME OWNS THE SCREEN, and that is what `_busy` means
    now: the selector, the editor, the camera window, the clip bar. Each
    of those covers the desk or takes the mouse, so a second one would be
    two overlays fighting over the same drag. `_take_screen` claims it
    atomically and `_free_screen` gives it back.

    THE CORNER CARDS ARE NOT THAT, and used to be treated as if they
    were. A card is 384×96 in a corner; it owns nothing. Holding `_busy`
    across its five seconds made the screenshot key dead for five seconds
    after every screenshot — the single most common thing to do with that
    key being the one thing it refused. So the cards live on their own
    long-lived deck (`ShotCards`) with the flag clear, they stack, and the
    key answers every press.

    Each screen-owning flow still owns its thread and its interpreter,
    built and destroyed and collected on that same thread, which is the
    rule overlay.py wrote down and AGENTS.md re-states in full. The deck
    obeys it too, from the other end: its interpreter is built once and
    never dies.
    """

    def __init__(self, cfg_provider, ask_provider=None, hush_overlays=None):
        self._cfg_of = cfg_provider       # () -> Config, read fresh: keys move
        # A CALLABLE, not the controller: the ask card is built lazily and
        # may be switched off entirely, and holding the object here would
        # build it the first time somebody took a screenshot.
        self._ask_of = ask_provider
        # ALSO A CALLABLE, `(bool) -> None`, and for a harder reason than
        # laziness. The overlay cards — the notification, the reading, the
        # hint — used to keep themselves out of the way with
        # WDA_EXCLUDEFROMCAPTURE; that flag went on 2026-09-04 because it
        # hid them from the OWNER's screenshots too, and what replaces it
        # is this: they are asked to come off the live screen for the
        # length of a selection, AFTER the desktop has been frozen, so
        # they are in the picture and out of the drag.
        #
        # Injected by main.py rather than imported, because capture.py
        # must not depend on overlay.py — this module is dragged in by a
        # keypress and overlay.py is on the startup path, and a test greps
        # for exactly that import. None when nobody wired it, which is
        # every test that builds a bare Controller.
        self._hush_overlays = hush_overlays
        self._busy = threading.Event()
        self._stop_clip = threading.Event()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._recorder: ScreenRecorder | None = None
        self._camera: Camera | None = None
        # BUILT ON THE FIRST CARD, not at start-up. The promise three
        # paragraphs up is that an owner who never presses the key pays
        # nothing for the idea of it, and a Tk root plus a live thread is
        # not nothing.
        self._cards: ShotCards | None = None

    # ---- what main.py reads (hook-thread safe) ----

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    @property
    def recording(self) -> bool:
        return self._recorder is not None

    def _cfg(self):
        cfg = getattr(self._cfg_of(), "capture", None)
        if cfg is None:
            raise CaptureError("this version of the app has no [capture] "
                               "section")
        return cfg

    @staticmethod
    def _cue(kind: str) -> None:
        try:
            import cues
            cues.play(kind)
        except Exception:
            pass

    # ---- who owns the screen ----

    def _take_screen(self, hush: bool = True) -> bool:
        """Claim the screen for a window that is about to cover it.

        ATOMIC, BECAUSE THREE FLOWS NOW RACE FOR IT. It used to be two
        hotkeys on one hook thread, where `if is_set(): return` followed
        by `set()` could not lose — but a card's Edit button starts a
        fourth claimant on a thread of its own, and check-then-set across
        two threads is the oldest bug there is. The `with` makes the
        answer to "may I" and the act of taking it one step.

        Hushing the cards is part of taking the screen and not a separate
        courtesy: a topmost card in the bottom-right would eat a drag
        that ended in that corner, and the bottom-right is where people
        drag TO.

        `hush=False` IS FOR THE SCREENSHOT KEY ALONE, and it is a
        two-step rather than a refusal: the screenshot flow wants the
        cards ON the desk for the length of one `ImageGrab`, so that a
        capture CAN be taken of them, and off it for the drag that
        follows. It therefore claims the screen without hushing and
        hushes itself the instant the freeze is in hand. The camera and
        the recorder have no such moment — nothing of theirs is
        photographed before their window maps — so they take the
        default.
        """
        with self._lock:
            if self._busy.is_set():
                return False
            self._busy.set()
        if hush:
            self._hush_cards()
        return True

    def _free_screen(self) -> None:
        """Give it back, and put the cards up again."""
        self._busy.clear()
        self._unhush_cards()

    def _hush_cards(self) -> None:
        deck = self._cards
        if deck is not None:
            deck.hush()
        self._hush_them(True)

    def _unhush_cards(self) -> None:
        deck = self._cards
        if deck is not None:
            deck.unhush()
        self._hush_them(False)

    def _hush_them(self, on: bool) -> None:
        """Ask main.py's overlay cards to get off the live screen, or to
        come back.

        SWALLOWS EVERYTHING, and that is deliberate. This runs on the
        keyboard hook by way of `begin_shot`, where hotkey.py's budget is
        300 ms and the failure mode of overrunning it is that Windows
        silently unhooks — "my hotkey stopped working", nothing logged.
        A card that cannot be hushed is a card in the corner of one
        screenshot; a raised exception here is the screenshot key itself.
        The callable only sets an Event, so there is nothing here to be
        slow, but the guard costs nothing and the alternative is a class
        of bug that takes a day to find.
        """
        hush = self._hush_overlays
        if hush is None:
            return
        try:
            hush(on)
        except Exception:
            log.debug("could not %s the overlay cards",
                      "hush" if on else "unhush", exc_info=True)

    def _deck(self) -> "ShotCards | None":
        """The corner-card deck, built on the FIRST card and never before.

        None when Tk is not there or the deck's thread refused to come
        up, and the caller falls back to a single standalone card. The
        feature degrades to what shipped before it; it does not vanish.

        Built OUTSIDE the lock — `start()` waits up to three seconds for
        the thread to answer, and holding `_lock` for three seconds would
        stall the very hotkey this exists to keep alive. Two threads
        racing here both build one and the loser buries its own.
        """
        deck = self._cards
        if deck is not None:
            return deck
        deck = ShotCards(self._cfg)
        if not deck.start():
            return None
        with self._lock:
            if self._cards is None:
                self._cards = deck
                deck = None
        if deck is not None:
            deck.stop()               # somebody else got there first
        return self._cards

    # ---- the screenshot key ----

    def begin_shot(self) -> bool:
        """Start the select-and-edit flow. False if one is already up."""
        # NOT HUSHED YET — _shot_flow does it, one line after the freeze,
        # so the cards already on the desk are IN that freeze and can be
        # captured. See _take_screen.
        if not self._take_screen(hush=False):
            return False
        self._cancel.clear()
        threading.Thread(target=self._shot_flow, daemon=True,
                         name="capture-shot").start()
        return True

    def _shot_flow(self) -> None:
        window = None
        try:
            from PIL import ImageGrab
            cfg = self._cfg()
            started = time.monotonic()
            full = ImageGrab.grab(all_screens=True).convert("RGB")
            # THE CARDS ARE IN THAT PICTURE, AND NOW THEY GET OUT OF THE
            # WAY. This one line is the whole reason the owner can
            # photograph his own stack: the freeze above caught the desk
            # as he sees it, cards and all, and the hush below takes them
            # off the live screen before the selector maps so they cannot
            # eat a drag over the corner they sit in. Hushing before the
            # grab — which is what taking the screen does for every other
            # flow — would have removed them from the picture as well.
            self._hush_cards()
            log.debug("capture froze %dx%d in %.0f ms", full.width,
                      full.height, (time.monotonic() - started) * 1000)
            window = ShotWindow(full, mode="shot", cfg=cfg,
                                folder=cfg.folder,
                                copy=cfg.copy_to_clipboard,
                                edit=(cfg.after_shot == "editor"),
                                save=cfg.always_save,
                                on_saved=lambda _p: self._cue("shot"),
                                on_ask=self._ask_of)
            result = window.run()
            window = None
            gc.collect()
            if result and "ask" in result:
                self._hand_to_ask(*result["ask"])
            elif result and cfg.after_shot == "toast":
                self._offer(full, result, cfg)
        except Exception:
            log.exception("the screenshot flow failed")
            self._cue("error")
        finally:
            window = None
            # ONLY HERE is the window unreachable: run()'s own collect fired
            # while this frame still held it, and a Tk widget tree is always
            # cyclic, so dropping the reference does not free it either. It
            # would sit in cyclic garbage until some OTHER thread tripped the
            # generational threshold and ran Tcl_DeleteInterp from the wrong
            # thread — an abort with no traceback. AGENTS.md tells the whole
            # story; this is the line that obeys it.
            gc.collect()
            self._free_screen()

    def _offer(self, full, result: dict, cfg) -> None:
        """Hand the capture to the corner-card deck and get out of the way.

        THE INTERRUPTION IS THE THING BEING FIXED HERE. An editor that
        opens over the whole screen after every capture makes the common
        case — drag, paste, carry on — pay for the rare one, and the
        common case is nine captures in ten. So the drag ends silently
        with the picture already on the clipboard, and a small card in a
        corner offers the rest for a few seconds.

        THIS METHOD USED TO RUN THAT CARD TO COMPLETION, on this thread,
        with `_busy` held — which is why the screenshot key was dead for
        the whole five seconds after every screenshot. It now returns as
        soon as the payload is on the deck's queue, and the flow's
        `finally` releases the screen a moment later. Press the key
        again and the second card joins the first.

        The frozen screen goes with it, which is what lets the editor
        open on the pixels as they WERE rather than as they are now —
        seconds are long enough for the window underneath to have
        scrolled. That is also the memory this costs, and `add` logs it.
        """
        if self._cancel.is_set():
            log.info("the app is shutting down — no card for this capture "
                     "(the picture is on your clipboard)")
            return
        deck = self._deck()
        if deck is None:
            return self._offer_alone(full, result, cfg)
        try:
            deck.add(result["image"], result["box"],
                     saved=result.get("path"),
                     corner=cfg.toast_corner,
                     seconds=cfg.toast_seconds,
                     copied=cfg.copy_to_clipboard,
                     in_shots=getattr(cfg, "toast_in_shots", True),
                     full=full,
                     on_action=lambda answer: self._card_action(
                         answer, full, result, cfg))
        except Exception:
            log.exception("the corner card could not be offered")
            self._offer_alone(full, result, cfg)

    def _card_action(self, answer: dict, full, result: dict, cfg) -> None:
        """A card was clicked. Start the work and RETURN AT ONCE.

        Called on the deck's pump thread, which is the one thread allowed
        to touch any card — so everything slow goes to a thread of its
        own or every other card's clock stops with it.
        """
        threading.Thread(target=self._edit_flow, daemon=True,
                         name="capture-card-action",
                         args=(answer.get("action"), full, result,
                               cfg)).start()

    def _edit_flow(self, action: str | None, full, result: dict,
                   cfg) -> None:
        """What Save and Edit on a card actually do.

        SAVE NEEDS NOTHING FROM THE SCREEN, so it just writes the file —
        two cards saved in the same second no longer collide, because
        save_image now holds a lock across the glob and the write.

        EDIT NEEDS THE WHOLE SCREEN, so it has to queue for it like every
        other flow. If the selector, the camera or a recording already has
        it, the honest answer is to say so and stop: an editor that opened
        LATER, over whatever the owner had moved on to, would be a window
        arriving out of nowhere — and nothing is lost by refusing, because
        the picture has been on the clipboard since the mouse came up.
        """
        editor = None
        try:
            if self._cancel.is_set():
                return
            if action == "save":
                path = save_image(result["image"], cfg.folder, kind="shot")
                log.info("screenshot saved on request: %s", path)
                self._cue("shot")
                return
            if action != "edit":
                return
            if not self._take_screen():
                log.info("something else owns the screen — the picture is "
                         "still on your clipboard")
                self._cue("error")
                return
            try:
                editor = ShotWindow(full, mode="shot", cfg=cfg,
                                    folder=cfg.folder,
                                    copy=cfg.copy_to_clipboard, edit=True,
                                    save=cfg.always_save,
                                    start_box=result["box"],
                                    start_shape=result.get("shape"),
                                    saved=result.get("path"),
                                    on_ask=self._ask_of)
                out = editor.run()
                if out and "ask" in out:
                    self._hand_to_ask(*out["ask"])
            finally:
                editor = None
                gc.collect()
                self._free_screen()
        except Exception:
            log.exception("the capture card's %s failed", action)
            self._cue("error")
        finally:
            editor = None
            gc.collect()

    def _offer_alone(self, full, result: dict, cfg) -> None:
        """One card, run to completion here, the way it worked before.

        THE FALLBACK, and it is deliberately today's exact path: the deck
        could not start (no Tk, or its thread never answered) and the
        answer to that is one card instead of none. `_busy` is already
        held by the flow that called this, so nothing else can take the
        screen while it is up — which is the old behaviour, including its
        one flaw, and that is the point of a fallback.
        """
        toast = editor = None
        try:
            toast = ShotToast(result["image"], result["box"],
                              saved=result.get("path"),
                              corner=cfg.toast_corner,
                              seconds=cfg.toast_seconds,
                              copied=cfg.copy_to_clipboard,
                              in_shots=getattr(cfg, "toast_in_shots", True))
            action = toast.run()
            toast = None
            gc.collect()
            if action == "save":
                path = save_image(result["image"], cfg.folder, kind="shot")
                log.info("screenshot saved on request: %s", path)
                self._cue("shot")
                return
            if action != "edit":
                return
            editor = ShotWindow(full, mode="shot", cfg=cfg,
                                folder=cfg.folder,
                                copy=cfg.copy_to_clipboard, edit=True,
                                save=cfg.always_save,
                                start_box=result["box"],
                                start_shape=result.get("shape"),
                                saved=result.get("path"),
                                on_ask=self._ask_of)
            out = editor.run()
            if out and "ask" in out:
                self._hand_to_ask(*out["ask"])
        finally:
            toast = editor = None
            gc.collect()

    def _hand_to_ask(self, image, box) -> None:
        """Send a finished shot to the ask card.

        Deliberately goes through visual_qa's own Controller rather than
        reaching into its window: the upload gate, the backend chain and
        the barge-in generation counter are all its business, and a second
        way in would be a second place for them to be got wrong.
        """
        ask = self._ask_of() if self._ask_of is not None else None
        if ask is None:
            return
        opener = getattr(ask, "open_with", None)
        if opener is None:
            log.info("this version's ask card cannot be handed a picture")
            return
        try:
            if not opener(image, box):
                log.info("the ask card is busy with something else")
        except Exception:
            log.exception("could not hand the capture to the ask card")

    # ---- the camera key ----

    def _camera_cfg(self):
        cfg = getattr(self._cfg_of(), "camera", None)
        if cfg is None:
            raise CaptureError("this version of the app has no [camera] "
                               "section")
        return cfg

    def begin_photo(self) -> bool:
        """Open the camera and offer the shutter. False if busy."""
        if not self._take_screen():
            return False
        self._cancel.clear()
        threading.Thread(target=self._photo_flow, daemon=True,
                         name="capture-photo").start()
        return True

    def _photo_flow(self) -> None:
        window = None
        # Every camera this flow opens, including any a switch left behind.
        # The window closes its own on the way out and closing a closed
        # camera is free — but an exception between opening one and handing
        # it to the window would otherwise leave a lens streaming with
        # nothing on screen to say so.
        opened: list[Camera] = []
        try:
            cfg = self._camera_cfg()
            names = cameras()
            if not names:
                self._cue("error")
                log.info("no camera found — DirectShow lists no video "
                         "device. Plug one in, or close whatever has it "
                         "open, and press '%s' again", cfg.hotkey)
                return
            name, note = self._choose(names, cfg.device)
            size = parse_size(cfg.size)
            preview = preview_fit(size, work_area_near(*_pointer()))
            camera = self._open_camera(name, size, preview, cfg,
                                       cfg.mirror, opened)
            window = CameraWindow(
                camera, names=names,
                open_camera=lambda other, mirror: self._open_camera(
                    other, size, preview, cfg, mirror, opened),
                folder=cfg.folder, copy=cfg.copy_to_clipboard,
                edit=cfg.edit_after_shot, timer=cfg.timer,
                hotkey=cfg.hotkey, on_saved=lambda _p: self._cue("shot"))
            if note:
                window.say(note, ttl_ms=8000)
            left, top, right, bottom = window.preview_rect()
            log.info("camera open on %r at %d×%d (shown at %d×%d, at "
                     "%d,%d) — space takes the picture, esc closes", name,
                     size[0], size[1], right - left, bottom - top, left, top)
            result = window.run()
            window = None
            gc.collect()          # the camera window's own interpreter,
                                  # freed here, by the thread that made it
            if result and result.get("backdrop") is not None:
                self._edit_photo(result, cfg)
        except Exception:
            log.exception("the camera flow failed")
            self._cue("error")
        finally:
            window = None
            for camera in opened:
                try:
                    camera.close()
                except Exception:
                    log.debug("closing the camera raised", exc_info=True)
            with self._lock:
                self._camera = None
            gc.collect()
            self._free_screen()

    @staticmethod
    def _choose(names: list[str], wanted: str) -> tuple[str, str]:
        """(the camera to open, what to say about it).

        A `device` that is set and not present falls back to the automatic
        pick and SAYS so on the window, rather than either refusing to
        open or opening a different camera in silence. The owner unplugs
        one webcam and plugs in another; the key should still take a
        picture, and he should still be told whose picture it is.
        """
        name = pick_camera(names, wanted)
        if name is not None:
            return name, ""
        name = pick_camera(names, "")
        note = f"no camera matching '{wanted}' — using {name}"
        log.info("%s (DirectShow lists: %s)", note, ", ".join(names))
        return name, note

    def _open_camera(self, name: str, size, preview, cfg, mirror: bool,
                     seen: list | None = None) -> Camera:
        camera = Camera(name, size=size, fps=cfg.fps, preview=preview,
                        mirror=mirror)
        if seen is not None:
            seen.append(camera)
        with self._lock:
            self._camera = camera
        camera.start()
        return camera

    def _edit_photo(self, result: dict, cfg) -> None:
        """Open the editor on the photo, where the photo already was.

        The trick, and it is the whole reason the camera key ends in the
        SAME editor as the screenshot key rather than one of its own: the
        photo is pasted into the frozen desktop at the rectangle the
        preview occupied, and the editor is told that rectangle. So the
        picture does not move. The preview freezes, the screen dims around
        it, and the toolbar arrives underneath the thing you were just
        looking at — which is exactly what a drag with the screenshot key
        does, and it is one behaviour to learn instead of two.

        No scaling happens here. preview_fit already made the preview and
        the file the same size for this reason.
        """
        window = None
        try:
            backdrop = result["backdrop"]
            image = result["photo"]
            box = result["box"]
            vx, vy, _vw, _vh = virtual_screen()
            backdrop.paste(image, (box[0] - vx, box[1] - vy))
            window = ShotWindow(backdrop, mode="shot", cfg=cfg,
                                folder=cfg.folder,
                                copy=cfg.copy_to_clipboard, edit=True,
                                kind="photo", start_box=box,
                                saved=result.get("path"),
                                on_ask=self._ask_of)
            out = window.run()
            if out and "ask" in out:
                self._hand_to_ask(*out["ask"])
        finally:
            window = None
            gc.collect()

    # ---- the recording key ----

    def toggle_clip(self) -> bool:
        """Tap once to choose a region and start, tap again to stop.

        A toggle rather than two keys because the second press is the same
        thought as the first — "that's the bit, and that's enough of it" —
        and because a recorder you cannot stop with the key that started
        it is a recorder you have to go and find with the mouse while it
        records you finding it.
        """
        if self._recorder is not None:
            self._stop_clip.set()
            return True
        if not self._take_screen():
            return False
        self._cancel.clear()
        self._stop_clip.clear()
        threading.Thread(target=self._clip_flow, daemon=True,
                         name="capture-clip").start()
        return True

    def _clip_flow(self) -> None:
        window = bar = toast = None
        try:
            from PIL import ImageGrab
            cfg = self._cfg()
            full = ImageGrab.grab(all_screens=True).convert("RGB")
            window = ShotWindow(full, mode="region", cfg=cfg,
                                folder=cfg.folder)
            chosen = window.run()
            window = None
            gc.collect()                 # the selector's interpreter, freed
            if not chosen:                                    # here, by the
                return                                        # thread that
            box = even_box(chosen["box"])                     # made it
            if box[2] - box[0] < 16 or box[3] - box[1] < 16:
                return self.say_small()
            recorder = self._new_recorder(box, cfg)
            with self._lock:
                self._recorder = recorder
            recorder.start()
            self._cue("recording")
            log.info("recording %d×%d to %s%s — tap '%s' again to stop",
                     box[2] - box[0], box[3] - box[1], recorder.path.name,
                     " with the microphone" if recorder.has_audio else "",
                     cfg.record_hotkey)
            bar = ClipBar(recorder, on_stop=self._stop_clip.set,
                          on_discard=lambda: setattr(recorder, "discard", True),
                          on_mic=recorder.toggle_mute,
                          corner=cfg.timer_corner, announce=cfg.announce,
                          stop_key=cfg.record_hotkey)
            bar.run(self._stop_clip)
            bar = None
            gc.collect()
            path = recorder.finish()
            self._cue("recorded")
            if recorder.discard:
                if path is not None:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                log.info("recording discarded")
                return
            if path is None:
                log.info("the recording captured no frames — nothing saved")
                return
            seconds = recorder.elapsed
            size = path.stat().st_size
            log.info("recording saved: %s (%s, %s, %d frames%s)", path,
                     elapsed_readout(seconds), size_readout(size),
                     recorder.frames_written,
                     f", {recorder.dropped} dropped" if recorder.dropped
                     else "")
            if cfg.copy_clip_path:
                copy_file(path)
            toast = Toast(path,
                          f"{elapsed_readout(seconds)}  ·  "
                          f"{size_readout(size)}"
                          f"{'  ·  copied' if cfg.copy_clip_path else ''}",
                          box, corner=cfg.timer_corner)
            toast.run()
        except Exception as e:
            log.exception("the screen recording failed")
            self._cue("error")
            log.info("recording stopped: %s", e)
        finally:
            window = bar = toast = None
            with self._lock:
                self._recorder = None
            gc.collect()
            self._free_screen()

    def _new_recorder(self, box, cfg) -> ScreenRecorder:
        directory = capture_dir(cfg.folder)
        taken = {p.name for p in directory.glob("clip *.mp4")}
        path = directory / capture_name("clip", taken=taken)
        # The SAME microphone dictation uses, when the owner asked for
        # sound at all. Two shared-mode input streams on one device were
        # verified working on this machine (2026-08-25), so a recording
        # does not cost you the hotkey — and if a driver ever refuses,
        # _listen loses the sound and keeps the picture.
        audio_cfg = getattr(self._cfg_of(), "audio", None)
        return ScreenRecorder(
            box, path, fps=cfg.fps, quality=cfg.quality, cursor=cfg.cursor,
            audio=(cfg.audio == "mic"),
            audio_device=getattr(audio_cfg, "device", None),
            max_seconds=cfg.max_minutes * 60)

    @staticmethod
    def say_small() -> None:
        log.info("that region is too small to record — nothing started")

    # ---- shutdown ----

    def stop(self) -> None:
        """Everything this controller started, stopped.

        `_cancel` HAS A READER NOW. It was set here and cleared in three
        places and read in NONE of them, which meant it announced a
        shutdown to nobody: a capture already in flight would put a card
        up on the way out, and the card would be the last thing left on a
        screen belonging to an app that had been asked to quit. `_offer`
        and `_edit_flow` both check it, so a flow that is mid-drag when
        the app is asked to close finishes quietly with the picture on
        the clipboard and nothing on screen.
        """
        self._cancel.set()
        self._stop_clip.set()
        recorder = self._recorder
        if recorder is not None:
            recorder.stop()
        # The lens goes dark when the app does, whatever the window was in
        # the middle of. A webcam still streaming after its process has
        # been asked to quit is the one failure of this feature nobody
        # would forgive.
        camera = self._camera
        if camera is not None:
            camera.close()
        # The deck last, and by its own thread: stop() enqueues a sentinel
        # and joins, so every card is destroyed and the root collected by
        # the thread that built them. Nothing here touches a Tk object.
        deck, self._cards = self._cards, None
        if deck is not None:
            deck.stop()
