"""Screen capture: a shot you can draw on, and a clip you can send.

Two keys, one folder. **ctrl+f11** freezes the screen and dims it, you drag
a rectangle (or hold Shift and lasso a shape) and let go: the picture is on
your clipboard and in `captures\\` before you have moved your hand, and a
glass toolbar opens under the selection so you can crop it, draw on it,
arrow at it or blur the part nobody else should read. **ctrl+f12** picks a
region the same way — or a whole monitor, by name, off a chip — and records
it to an mp4 until you tap the key again, announcing itself in a corner and
then shrinking to a red dot and a clock.

It is Win+Shift+S, plus the editor, plus a recorder, written to the same
rules as the rest of this app: nothing leaves the machine, everything is
measured, and the pixels are yours.

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
  answer here is the same — `Controller._flow` runs `gc.collect()` in a
  `finally` once the window is unreachable, and only then clears `_busy`.
- **h264 wants even dimensions.** yuv420p subsamples chroma by two, so an
  odd-width region is a libx264 error at `container.add_stream` time, long
  after the user has started recording. `even_box` shrinks the rectangle
  by a pixel before anything is opened.

PRIVACY, stated plainly because it decides the defaults
--------------------------------------------------------
Unlike the ask card — which holds its screenshot in memory and never
writes it down — this feature's whole job is to write it down. So the
folder is treated the way transcripts.log is: it lives beside the app, it
is gitignored, and nothing in it is ever uploaded anywhere by this module.
There is no cloud path in this file at all; the only way a capture reaches
a model is the Ask button, which hands the pixels to visual_qa and obeys
`visual_qa.allow_screenshot_upload` like every other question.

The microphone is OFF by default in a recording (`[capture] audio =
"off"`) and there is a switch on the clip bar to turn it on for the clip
you are recording. A screen recorder that quietly opens the mic is a
surprise, and this app's rule is that audio does not travel — a recording
you make on purpose is you choosing otherwise, once, visibly.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import gc
import io
import logging
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
PIXEL_BLOCK = 12             # the redaction mosaic; below ~8 px, 12 pt
                             # text is still readable in the blocks

# The toolbar. One row of round chips and pill buttons, one line of text.
CHIP = 34
GAP = 7
BAR_PAD_X, BAR_PAD_Y = 14, 12
BAR_H = 82
BAR_RADIUS = 22
BAR_GAP = 18                 # between the selection and the toolbar

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

# 1/1000 s. Wall-clock presentation stamps rather than frame numbers, so a
# clip that could only manage 24 fps plays at real speed instead of fast.
CLOCK_HZ = 1000


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
    """
    suffix = {"shot": ".png", "clip": ".mp4"}[kind]
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
    """
    try:
        import win32clipboard
        import win32con
        dib, png = _image_formats(image)
        cf_png = win32clipboard.RegisterClipboardFormat("PNG")
        injector = _injector()
        opener = getattr(injector, "_open_clipboard", None)
        if opener is not None:
            opener()                    # the retry loop injector.py already
        else:                           # paid for: another app may hold it
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


def _arrow_head(start, end, size: int = 17):
    """The two barbs of an arrow, as a filled triangle.

    Drawn from the geometry rather than as a rotated bitmap so it stays
    sharp at any angle and any length, and so a very short arrow still
    gets a head proportional to the line instead of a blob bigger than it.
    """
    import math
    x0, y0 = start
    x1, y1 = end
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return []
    size = min(size, max(6, length * 0.42))
    angle = math.atan2(y1 - y0, x1 - x0)
    spread = math.radians(26)
    return [(x1, y1),
            (x1 - size * math.cos(angle - spread),
             y1 - size * math.sin(angle - spread)),
            (x1 - size * math.cos(angle + spread),
             y1 - size * math.sin(angle + spread))]


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
    """
    from PIL import Image, ImageDraw
    dx, dy = origin
    out = image.convert("RGBA")
    for mark in marks:
        kind = mark["kind"]
        colour = tuple(mark.get("colour", INKS[0][1]))
        points = _shift(mark.get("points", ()), dx, dy)
        if kind == "blur":
            if len(points) >= 2:
                out = pixelate(out, (points[0][0], points[0][1],
                                     points[-1][0], points[-1][1]))
            continue
        if kind == "highlight":
            # ITS OWN LAYER, because ImageDraw's fill REPLACES pixels: a
            # translucent line drawn straight on would cut a hole through
            # the screenshot rather than tint it.
            if len(points) < 2:
                continue
            layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).line(points, fill=colour + (HIGHLIGHT_A,),
                                       width=HIGHLIGHT_W, joint="curve")
            out = Image.alpha_composite(out, layer)
            continue
        draw = ImageDraw.Draw(out)
        if kind == "pen" and len(points) >= 2:
            draw.line(points, fill=colour + (255,), width=PEN_W,
                      joint="curve")
        elif kind == "arrow" and len(points) >= 2:
            draw.line([points[0], points[-1]], fill=colour + (255,),
                      width=PEN_W)
            head = _arrow_head(points[0], points[-1])
            if head:
                draw.polygon(head, fill=colour + (255,))
        elif kind == "box" and len(points) >= 2:
            left, top, right, bottom = normalize_bbox(
                points[0][0], points[0][1], points[-1][0], points[-1][1])
            draw.rounded_rectangle((left, top, right, bottom), 4,
                                   outline=colour + (255,), width=BOX_W)
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


def save_image(image, folder: str, when: float | None = None) -> Path:
    """Write a shot and return where it went."""
    directory = capture_dir(folder)
    taken = {p.name for p in directory.glob("shot *.png")}
    path = directory / capture_name("shot", when, taken)
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
            block = self.audio_rate // 10
            with sd.InputStream(samplerate=self.audio_rate, channels=1,
                                dtype="int16", device=self.audio_device,
                                blocksize=block) as stream:
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
            log.info("the recording has no sound (%s) — the picture is "
                     "unaffected", e)


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
    else:
        raise ValueError(f"no such icon: {kind}")
    return img.resize((size, size), Image.LANCZOS)


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
                 edit: bool = True, on_saved=None, on_ask=None):
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

        self.root = tk.Tk()
        self.phase = "select"
        self.box: tuple[int, int, int, int] | None = None
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
        self._layout = bar_layout()
        self._hover: str | None = None
        self._dirty = True

        self._build()

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
        self._draw_hint(px, py)

        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_move)
        root.bind_all("<Return>", self._on_enter)
        root.bind_all("<KP_Enter>", self._on_enter)

    def _draw_hint(self, px: int, py: int) -> None:
        """The one line of instructions, on the monitor the pointer is on.

        Not in the middle of the VIRTUAL screen: on a two-monitor desk
        that is a bezel. Same reason visual_qa's selector asks
        work_area_near first.
        """
        from PIL import ImageTk
        verb = "capture" if self.mode == "shot" else "record"
        text = (f"Drag a box   ·   Shift-drag to lasso   ·   "
                f"or pick a whole screen below   ·   Esc cancels")
        if self.mode == "region":
            text = (f"Drag the area to {verb}   ·   or pick a whole screen "
                    f"below   ·   Esc cancels")
        width, height = 30 + 7 * len(text), 38
        hl, ht, hr, hb = work_area_near(px, py)
        x = (hl + hr) // 2 - width // 2 - self._vx
        y = ht + 56 - self._vy
        self._keep["hint"] = ImageTk.PhotoImage(
            _vq._rounded_pil(width, height, 10, CARD, SELECT_BG, STROKE),
            master=self.root)
        self.canvas.create_image(x, y, anchor="nw", image=self._keep["hint"],
                                 tags="hint")
        self.canvas.create_text(x + width // 2, y + height // 2, text=text,
                                fill=DIM, font=(_vq._pick_face(), 9),
                                tags="hint")
        self._plan_chips((hl + hr) // 2 - self._vx, y + height + 12)
        self._draw_chips()

    def _plan_chips(self, centre_x: int, top_y: int) -> None:
        """A chip per monitor, and one for the whole desktop.

        "Record the screen" was the ask, and a drag from corner to corner
        is not a way to say it — it is impossible to land exactly and it is
        the commonest thing anyone wants. Enter still means "the screen the
        pointer is on"; these say WHICH, out loud, which is the part that
        cannot be guessed from an empty dimmed desktop.

        Laid out here and drawn separately so the hover highlight can
        repaint without recomputing the row.
        """
        screens = monitors()
        entries = []
        for entry in screens:
            left, top, right, bottom = entry["rect"]
            entries.append((entry["label"],
                            f"{right - left} × {bottom - top}",
                            entry["rect"], entry["primary"]))
        if len(screens) > 1:
            vx, vy, vw, vh = virtual_screen()
            entries.append(("All screens", f"{vw} × {vh}",
                            (vx, vy, vx + vw, vy + vh), False))
        face = _vq._pick_face()
        height = 34
        widths = [max(118, 34 + 7 * len(f"{label}   {size}"))
                  for label, size, _rect, _primary in entries]
        total = sum(widths) + 8 * (len(widths) - 1)
        x = centre_x - total // 2
        self._chips = {}
        for (label, size, rect, primary), width in zip(entries, widths):
            self._chips[label] = {
                "box": (x, top_y, x + width, top_y + height),
                "target": rect, "size": size, "primary": primary,
                "face": face}
            x += width + 8

    def _draw_chips(self) -> None:
        from PIL import ImageTk
        canvas = self.canvas
        canvas.delete("chips")
        if self._hint_id is False:
            return
        for label, chip in self._chips.items():
            x0, y0, x1, y1 = chip["box"]
            hot = (label == self._chip_hover)
            key = f"chip{label}{hot}"
            self._keep[key] = ImageTk.PhotoImage(
                _vq._rounded_pil(x1 - x0, y1 - y0, 9,
                                 CARD_HI if hot else CARD, SELECT_BG,
                                 ACCENT if hot else STROKE),
                master=self.root)
            canvas.create_image(x0, y0, anchor="nw", image=self._keep[key],
                                tags="chips")
            canvas.create_text(x0 + (x1 - x0) // 2, (y0 + y1) // 2,
                               text=f"{label}   {chip['size']}",
                               fill=FG if hot else DIM,
                               font=(chip["face"], 9), tags="chips")

    def _drop_hint(self) -> None:
        if self._hint_id is not False:
            self.canvas.delete("hint")
            self.canvas.delete("chips")
            self._hint_id = False
            self._chips = {}

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
                self._draw_chips()
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
        self.path = path
        if self.mode == "region":
            self.result = {"box": self.box}
            return self.close()
        self._first_save()
        if not self.edit:
            # edit_after_shot = false makes this key a pure "grab it and
            # get out of my way". The file and the clipboard are identical
            # either way — the editor is an offer, never a step.
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
        try:
            self.saved_path = save_image(image, self.folder)
        except Exception as e:
            log.exception("could not save the screenshot")
            self.say(f"could not save: {e}", ttl_ms=6000)
            return
        copied = copy_image(image) if self.copy else False
        self.say(f"{'copied · ' if copied else ''}{self.saved_path.name}")
        log.info("screenshot %d×%d saved to %s%s",
                 image.width, image.height, self.saved_path,
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
                return self._activate(name)
        left, top, right, bottom = self.box
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
                arrowshape=(16, 18, 6), tags="ink")]
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
            box = clamp_box((start[0], start[1], end[0], end[1]), self.box)
            if box[2] - box[0] < 16 or box[3] - box[1] < 16:
                return
            self._push_history()
            self._crop_to(box)
            return
        self._push_history()
        self.marks.append({"kind": self.tool, "points": list(points),
                           "colour": INKS[self.ink][1]})
        self._dirty = True

    def _crop_to(self, box) -> None:
        """Narrow the shot.

        The marks keep their VIRTUAL-SCREEN coordinates through this, so a
        crop is one number changing and an undo puts the rectangle back
        with every mark still where it was drawn — including the ones the
        crop had cut off the edge.
        """
        self.box = box
        self.path = None                 # a crop of a lasso is a rectangle
        self.say(f"cropped to {selection_readout(box)}")
        self._dirty = True

    def _activate(self, name: str) -> None:
        if name in dict((t[0], t) for t in TOOLS):
            self.tool = name
            self.say({"pen": "draw", "arrow": "drag an arrow",
                      "box": "drag a box", "highlight": "drag to highlight",
                      "blur": "drag over what should not be readable",
                      "crop": "drag the part to keep"}[name])
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
            if copy_image(self.picture()):
                self.say("copied", ttl_ms=FLASH_MS)
            else:
                self.say("the clipboard would not take it")
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
                self.saved_path = save_image(image, self.folder)
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

        # The lit selection, its halo and its edge, computed on a CROP
        # around the rectangle rather than over the whole screen: a
        # full-screen blur here was 500 ms of the ask card's first draft.
        pad = 46
        hx0 = max(0, left - self._vx - pad)
        hy0 = max(0, top - self._vy - pad)
        hx1 = min(self.dark.width, right - self._vx + pad)
        hy1 = min(self.dark.height, bottom - self._vy + pad)
        local = self.dark.crop((hx0, hy0, hx1, hy1)).convert("RGBA")
        lw, lh = local.size
        ox, oy = left - self._vx - hx0, top - self._vy - hy0
        ex, ey = ox + (right - left), oy + (bottom - top)
        halo = Image.new("L", (lw, lh), 0)
        ImageDraw.Draw(halo).rounded_rectangle((ox - 3, oy - 3, ex + 3, ey + 3),
                                               14, outline=255, width=16)
        halo = halo.filter(ImageFilter.GaussianBlur(9)).point(
            lambda v: int(v * .45))
        local.alpha_composite(Image.merge("RGBA", (
            Image.new("L", (lw, lh), 86), Image.new("L", (lw, lh), 156),
            Image.new("L", (lw, lh), 245), halo)))
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
            _user32.GetAsyncKeyState(0x1B)     # prime, discard
            while not self._closing:
                # ESCAPE IS READ, NOT RECEIVED — a borderless topmost
                # overlay does not get the keyboard focus for free, and
                # taking it with the Alt tap arms the menu bar of whatever
                # is underneath and eats the click that starts the drag.
                # Both halves of GetAsyncKeyState, or a tap between two
                # ticks is lost. Same call, same reasons, as the selector.
                pressed = _user32.GetAsyncKeyState(0x1B)
                if pressed & 0x8000 or pressed & 0x0001:
                    break
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

class Controller:
    """What main.py holds: two hotkeys land here.

    Constructing one is cheap and imports nothing heavy — Pillow, Tk, PyAV
    and sounddevice all load on the first press, so an owner who never
    presses either key pays nothing for the idea of them.

    Both flows are strictly sequential and own their thread: the selector
    closes before the editor opens, the editor closes before a recording
    starts. One Tk interpreter at a time, built and destroyed and
    collected on the same thread, which is the rule overlay.py wrote down
    and AGENTS.md re-states in full.
    """

    def __init__(self, cfg_provider, ask_provider=None):
        self._cfg_of = cfg_provider       # () -> Config, read fresh: keys move
        # A CALLABLE, not the controller: the ask card is built lazily and
        # may be switched off entirely, and holding the object here would
        # build it the first time somebody took a screenshot.
        self._ask_of = ask_provider
        self._busy = threading.Event()
        self._stop_clip = threading.Event()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._recorder: ScreenRecorder | None = None

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

    # ---- the screenshot key ----

    def begin_shot(self) -> bool:
        """Start the select-and-edit flow. False if one is already up."""
        if self._busy.is_set():
            return False
        self._busy.set()
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
            log.debug("capture froze %dx%d in %.0f ms", full.width,
                      full.height, (time.monotonic() - started) * 1000)
            window = ShotWindow(full, mode="shot", cfg=cfg,
                                folder=cfg.folder,
                                copy=cfg.copy_to_clipboard,
                                edit=cfg.edit_after_shot,
                                on_saved=lambda _p: self._cue("shot"),
                                on_ask=self._ask_of)
            result = window.run()
            if result and "ask" in result:
                self._hand_to_ask(*result["ask"])
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
            self._busy.clear()

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
        if self._busy.is_set():
            return False
        self._busy.set()
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
            self._busy.clear()

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
        self._cancel.set()
        self._stop_clip.set()
        recorder = self._recorder
        if recorder is not None:
            recorder.stop()
