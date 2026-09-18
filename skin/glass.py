"""A sheet of glass over the desktop, that Skia paints on.

WHY THIS IS NOT A TK WINDOW, WHICH IS WHAT EVERYTHING ELSE HERE USES.

Three of this repo's most expensive lessons all point the same way for a
window that is nothing but a picture:

  * "Tk takes the foreground the moment it REALISES a window, and
    WS_EX_NOACTIVATE does not stop it" (AGENTS.md, measured 2026-08-26).
    The documented fix is to take the foreground back afterwards with
    SetForegroundWindow. A plain CreateWindowExW window shown with
    SW_SHOWNOACTIVATE never takes it in the first place, so there is
    nothing to give back and no window between the two states.

  * "A Tk window must be COLLECTED by the thread that built it, not just
    destroyed there" — the Tcl_AsyncDelete abort that took the app down
    twice. There is no interpreter here, so that whole class of bug does
    not exist on this path.

  * "UpdateLayeredWindow gives true per-pixel alpha and ERASES TK." That
    is written as a warning because the ask card needs live widgets. This
    window has none: erasing Tk is not a cost here, it is the point.
    UpdateLayeredWindow is the only route on Windows to true per-pixel
    alpha over the desktop, and per-pixel alpha is the entire difference
    between light and cut-out cardboard. Measured on this machine: a
    chroma key cannot do it, because Tk antialiases nothing (0 intermediate
    shades in a 400x400 grab) and PIL antialiases everything, so a keyed
    window is either stair-cased or fringed. There is no third setting.

HOW A FRAME IS MADE, AND WHY THERE ARE TWO WAYS.

On the GPU (skin/gl.py), Skia draws into a render target and the finished
frame is read back straight into the DIB the layered window is about to be
handed. The readback is 4.33 ms at 2560x1440 and everything drawn before it
is effectively free — measured on this machine, a full-screen bloom with a
90 px Gaussian blur composited over the desktop runs at 154 fps.

Without a GPU, Skia wraps the DIB's own bytes with MakeRasterDirect, so the
frame is drawn once and never copied. That path is correct and much slower:
the CPU rasteriser blends at 64 ns a pixel, which makes one full-screen
translucent fill 238 ms. Anything drawn for the fallback has to be built
out of small shapes and hard edges — see skin/burst.py, which is written to
that budget and therefore looks right on both.

Every ctypes handle here is a PRIVATE ctypes.WinDLL. `ctypes.windll.user32`
is a process-global cached object and five files here reach for the same
one; capture.py declaring GetDC.restype broke visual_qa.text_pil on a line
that had worked for months. A new wrapper has its own function cache.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import logging

_log = logging.getLogger("app")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

_user32.GetDC.restype = ctypes.c_void_p
_user32.GetDC.argtypes = [ctypes.c_void_p]
_user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.CreateWindowExW.restype = ctypes.c_void_p
_user32.CreateWindowExW.argtypes = [
    w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p]
_user32.DefWindowProcW.restype = ctypes.c_longlong
_user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.c_size_t, ctypes.c_longlong]
_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.DestroyWindow.argtypes = [ctypes.c_void_p]
_user32.UpdateLayeredWindow.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD]
_user32.UpdateLayeredWindow.restype = ctypes.c_bool
_user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_uint]
_user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                          ctypes.c_void_p, ctypes.c_uint]
# Declared, not left to ctypes' defaults: an undeclared argument is passed
# as a C int, and an HWND is a 64-bit handle. It happens to work while
# handles stay small, which is exactly the kind of bug that appears on
# someone else's machine after a long uptime.
_user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.GetWindowRect.restype = ctypes.c_bool
_gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi32.CreateDIBSection.restype = ctypes.c_void_p
_gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_uint,
                                    ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.c_void_p, ctypes.c_uint]
_gdi32.SelectObject.restype = ctypes.c_void_p
_gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
_gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020      # click-through: the mouse never sees it
WS_EX_NOACTIVATE = 0x08000000       # a click never focuses it
WS_EX_TOOLWINDOW = 0x00000080       # never in the taskbar or Alt-Tab
WS_EX_TOPMOST = 0x00000008
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x00000002
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
HWND_TOPMOST = ctypes.c_void_p(-1)
SPI_GETCLIENTAREAANIMATION = 0x1042
ERROR_CLASS_ALREADY_EXISTS = 1410

# The hit-test answers a window may give. HTTRANSPARENT is the important
# one: it hands the click to whatever is underneath, which is how a window
# can be draggable by one strip and click-through everywhere else.
WM_NCHITTEST = 0x0084
WM_NCLBUTTONUP = 0x00A2
WM_LBUTTONDOWN = 0x0201
WM_EXITSIZEMOVE = 0x0232
HTTRANSPARENT = -1
HTCLIENT = 1
HTCAPTION = 2


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_void_p,
                              ctypes.c_uint, ctypes.c_size_t,
                              ctypes.c_longlong)


class _WNDCLASS(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


CLASS_NAME = "DeskITSkinGlass"
_proc_ref = None                 # Windows calls this; it must outlive us
_registered = False
# hwnd -> Glass, for the one message that needs to reach the instance.
# One shared window class serves every glass window in the process, so the
# proc cannot close over a single one of them.
_live: dict[int, "Glass"] = {}


def _proc(hwnd, msg, wparam, lparam):
    """Everything is DefWindowProc except the mouse, and the mouse only
    matters for a window that asked to be interactive.

    HTTRANSPARENT is returned for every pixel a window has not claimed,
    which is what keeps the close button of a maximised window clickable
    underneath a card sitting in that corner — the trap the status dot
    already paid for once.
    """
    try:
        glass = _live.get(int(hwnd or 0))
        if glass is not None and glass.hit is not None:
            if msg == WM_NCHITTEST:
                # lparam is screen coords, low word x, high word y, signed.
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                return glass.hit(x - glass.x, y - glass.y)
            if msg == WM_LBUTTONDOWN and glass.clicked:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                glass.clicked(x, y)        # already window-relative here
                return 0
            if msg in (WM_EXITSIZEMOVE, WM_NCLBUTTONUP) and glass.moved:
                glass.moved()
    except Exception:
        _log.debug("glass window proc", exc_info=True)
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _register() -> None:
    global _proc_ref, _registered
    if _registered:
        return
    _proc_ref = _WNDPROC(_proc)
    cls = _WNDCLASS()
    cls.lpfnWndProc = _proc_ref
    cls.lpszClassName = CLASS_NAME
    cls.hInstance = None
    if not _user32.RegisterClassW(ctypes.byref(cls)):
        err = ctypes.get_last_error()
        if err != ERROR_CLASS_ALREADY_EXISTS:
            raise ctypes.WinError(err)
    _registered = True


def virtual_screen() -> tuple[int, int, int, int]:
    """(x, y, w, h) of the whole desktop, monitors included.

    GetSystemMetrics, not Tk: winfo_screenwidth is the PRIMARY only, and
    this machine's second monitor starts at x = -1920.
    """
    g = _user32.GetSystemMetrics
    return g(76), g(77), g(78), g(79)


def primary_screen() -> tuple[int, int]:
    return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


def work_area() -> tuple[int, int, int, int]:
    """The primary monitor's work area — taskbar excluded."""
    rect = w.RECT()
    SPI_GETWORKAREA = 0x0030
    if _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                     ctypes.byref(rect), 0):
        return (rect.left, rect.top,
                rect.right - rect.left, rect.bottom - rect.top)
    pw, ph = primary_screen()
    return 0, 0, pw, ph


def wants_motion() -> bool:
    """The Windows equivalent of prefers-reduced-motion.

    A full-screen radial expansion is exactly the class of motion that
    triggers vestibular symptoms, and a user-triggered animation with no
    way off is a WCAG 2.3.3 failure. Windows has had the setting since
    Vista (Settings > Accessibility > Visual effects > Animation effects);
    it costs one call to honour it.
    """
    try:
        flag = ctypes.c_int(1)
        if _user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0,
                                         ctypes.byref(flag), 0):
            return bool(flag.value)
    except Exception:
        pass
    return True


class Glass:
    """A topmost, click-through, never-focusable layer that Skia paints.

    Build it, draw on `canvas`, call `flush()`. `close()` releases the GDI
    objects and the window; it is safe to call twice.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 gpu: bool = True, hit=None, moved=None, clicked=None) -> None:
        import skia                       # deferred: see skin/__init__

        self.x, self.y = int(x), int(y)
        self.width, self.height = int(width), int(height)
        # hit(x, y) -> one of the HT* codes, in window-relative pixels.
        # None keeps the old behaviour exactly: WS_EX_TRANSPARENT, and the
        # mouse never sees the window at all. Passing one drops that style
        # and hands every pixel to this function instead, which must
        # answer HTTRANSPARENT for anything it does not want.
        self.hit = hit
        self.moved = moved               # called after a drag finishes
        self.clicked = clicked           # called for a click on HTCLIENT
        self.hwnd = None
        self.dc = None
        self._bitmap = None
        self._old = None
        self.surface = None
        self.canvas = None
        self.on_gpu = False
        self._gr = None
        self._info = None

        _register()
        style = (WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
                 | WS_EX_TOPMOST)
        if hit is None:
            style |= WS_EX_TRANSPARENT
        self.hwnd = _user32.CreateWindowExW(
            style, CLASS_NAME, "", WS_POPUP,
            self.x, self.y, self.width, self.height,
            None, None, None, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        # Registered AFTER the handle exists and removed in close(), so a
        # message arriving on a half-built or half-dead window finds
        # nothing and falls through to DefWindowProc.
        if hit is not None or moved is not None or clicked is not None:
            _live[int(self.hwnd)] = self

        screen = _user32.GetDC(None)
        try:
            self.dc = _gdi32.CreateCompatibleDC(screen)
            info = _BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            info.bmiHeader.biWidth = self.width
            info.bmiHeader.biHeight = -self.height       # top-down rows
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0             # BI_RGB
            bits = ctypes.c_void_p()
            self._bitmap = _gdi32.CreateDIBSection(
                self.dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
            if not self._bitmap:
                raise ctypes.WinError(ctypes.get_last_error())
            self._old = _gdi32.SelectObject(self.dc, self._bitmap)
        finally:
            _user32.ReleaseDC(None, screen)

        nbytes = self.width * self.height * 4
        self._buf = (ctypes.c_char * nbytes).from_address(bits.value)
        self._view = memoryview(self._buf)
        # BGRA premultiplied, which is what a 32-bit top-down DIB is and
        # what UpdateLayeredWindow wants. Naming it explicitly rather than
        # taking N32 means the readback below cannot silently swap the
        # red and blue channels on some other machine's byte order.
        self._info = skia.ImageInfo.Make(self.width, self.height,
                                         skia.kBGRA_8888_ColorType,
                                         skia.kPremul_AlphaType)

        # THE GPU PATH. Skia's CPU rasteriser blends at 64 ns a pixel here,
        # which puts a full-screen translucent fill at 238 ms and makes
        # every soft, large, lovely thing unaffordable. On the GPU the same
        # fill is 0.07 ms and a 60 px Gaussian blur is 0.09. The whole cost
        # moves into one 4.3 ms readback per frame, which is a price worth
        # paying about three thousand times over.
        #
        # The surface is a render target rather than a wrapper round the
        # DIB, so a frame ends with readPixels straight into the DIB's own
        # bytes. No intermediate buffer, no conversion.
        if gpu:
            try:
                from . import gl
                ctx = gl.acquire()
                if ctx is not None:
                    surface = ctx.surface(self.width, self.height)
                    if surface is not None:
                        self.surface = surface
                        self._gr = ctx
                        self.on_gpu = True
            except Exception:
                _log.debug("skin: GPU surface refused", exc_info=True)

        if self.surface is None:
            self.surface = skia.Surface.MakeRasterDirect(
                self._info, self._view, self.width * 4)
        if self.surface is None:
            raise RuntimeError("Skia would not wrap the layered window's DIB")
        self.canvas = self.surface.getCanvas()

        self._src = _POINT(0, 0)
        self._dst = _POINT(self.x, self.y)
        self._size = _SIZE(self.width, self.height)
        self._blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    def show(self) -> None:
        _user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def hide(self) -> None:
        """Off the screen and kept: the dot while the model is off."""
        _user32.ShowWindow(self.hwnd, 0)                # SW_HIDE

    def raise_(self) -> None:
        """Back to the top of the z-order without taking focus. Another
        app going topmost mid-animation would otherwise cover us."""
        try:
            _user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def move(self, x: int, y: int) -> None:
        self.x, self.y = int(x), int(y)
        self._dst = _POINT(self.x, self.y)

    def flush(self, alpha: float = 1.0) -> bool:
        """Push the frame. `alpha` is a whole-window multiplier on top of
        the per-pixel alpha, which is how a finished effect fades out
        without every element having to fade itself."""
        if self.surface is None or self.hwnd is None:
            return False
        self.surface.flushAndSubmit()
        if self.on_gpu:
            # the one cost of the GPU path: 4.33 ms at 2560x1440, straight
            # into the DIB the layered window is about to be handed
            if not self.surface.readPixels(self._info, self._view,
                                           self.width * 4, 0, 0):
                return False
        self._blend.SourceConstantAlpha = max(0, min(255, int(alpha * 255)))
        return bool(_user32.UpdateLayeredWindow(
            self.hwnd, None, ctypes.byref(self._dst), ctypes.byref(self._size),
            self.dc, ctypes.byref(self._src), 0, ctypes.byref(self._blend),
            ULW_ALPHA))

    def pump(self) -> None:
        """Drain this window's messages so Windows never calls it hung."""
        msg = w.MSG()
        while _user32.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, 1):
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def where(self) -> tuple[int, int]:
        """Where the window actually is now.

        A drag done by HTCAPTION is Windows moving the window, not us, so
        `self.x` is stale afterwards and the position that gets saved has
        to be read back off the handle rather than remembered.
        """
        if not self.hwnd:
            return self.x, self.y
        rect = w.RECT()
        if _user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            self.x, self.y = int(rect.left), int(rect.top)
            self._dst = _POINT(self.x, self.y)
        return self.x, self.y

    def close(self) -> None:
        try:
            _live.pop(int(self.hwnd or 0), None)
            self.surface = None
            self.canvas = None
            self._gr = None
            self._view = None
            self._buf = None                 # release the DIB's memory view
            if self.dc:
                if self._old:
                    _gdi32.SelectObject(self.dc, self._old)
                if self._bitmap:
                    _gdi32.DeleteObject(self._bitmap)
                _gdi32.DeleteDC(self.dc)
            if self.hwnd:
                _user32.DestroyWindow(self.hwnd)
        except Exception:
            _log.debug("glass teardown", exc_info=True)
        finally:
            self.dc = self._bitmap = self._old = self.hwnd = None

    def __enter__(self) -> "Glass":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
