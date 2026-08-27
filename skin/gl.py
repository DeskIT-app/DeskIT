"""An OpenGL context, so Skia can use the graphics card.

WHY THIS FILE EXISTS, IN ONE MEASUREMENT. skia-python's CPU rasteriser
blends at 64 ns a pixel on this machine — perfectly linear, unchanged by
colour type, alpha type or colour space, and about twenty times slower
than a naive scalar loop has any right to be. At 2560x1440 that makes a
single full-screen translucent fill cost 238 ms. Every soft, large, lovely
thing — bloom, a wide glow, a real blur — was therefore unaffordable, and
the first design was bent around avoiding them.

The same operations on the GPU, measured on this machine's RTX 5060 Ti
through this file:

    full-screen 42% alpha fill ............ 0.07 ms   (3400x faster)
    full-screen radial gradient ........... 0.07 ms
    that gradient + a 60 px GAUSSIAN blur . 0.09 ms
    readPixels 2560x1440 .................. 4.33 ms

So the readback is the entire price, and it is one fixed 4.3 ms. Everything
drawn before it is free. That is the difference between "what can we afford
to draw" and "what should we draw".

skia-python ships GrDirectContext.MakeGL but no windowing, so the context
is built by hand: a hidden 8x8 window that is never shown, a pixel format,
and wglCreateContext. ~270 ms, paid once, during the model load.

TWO RULES THIS FILE OBEYS.

  A GL CONTEXT BELONGS TO ONE THREAD. wglMakeCurrent binds it to the
  calling thread and it may not be used from another. The contexts are kept
  in a threading.local, so whichever thread asks gets its own — and the
  status dot, which lives on its own thread and draws a 38 px circle, is
  never given one at all. It does not need 3400x on 1,444 pixels.

  A DECORATION MAY NOT BE FATAL. Every failure path here returns None:
  no GPU, a remote session, a driver that will not give a context, a Skia
  build without GL. The caller falls back to the CPU raster surface and the
  app looks slightly less good and works exactly the same.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import logging
import threading

_log = logging.getLogger("app")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_opengl32 = ctypes.WinDLL("opengl32", use_last_error=True)

_user32.CreateWindowExW.restype = ctypes.c_void_p
_user32.CreateWindowExW.argtypes = [
    w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p]
_user32.DefWindowProcW.restype = ctypes.c_longlong
_user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.c_size_t, ctypes.c_longlong]
_user32.GetDC.restype = ctypes.c_void_p
_user32.GetDC.argtypes = [ctypes.c_void_p]
_user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.DestroyWindow.argtypes = [ctypes.c_void_p]
_gdi32.ChoosePixelFormat.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi32.SetPixelFormat.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                  ctypes.c_void_p]
_opengl32.wglCreateContext.restype = ctypes.c_void_p
_opengl32.wglCreateContext.argtypes = [ctypes.c_void_p]
_opengl32.wglMakeCurrent.restype = ctypes.c_bool
_opengl32.wglMakeCurrent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_opengl32.wglDeleteContext.argtypes = [ctypes.c_void_p]
_opengl32.glGetString.restype = ctypes.c_char_p
_opengl32.glGetString.argtypes = [ctypes.c_uint]

PFD_DOUBLEBUFFER = 0x00000001
PFD_DRAW_TO_WINDOW = 0x00000004
PFD_SUPPORT_OPENGL = 0x00000020
CS_OWNDC = 0x0020
WS_POPUP = 0x80000000
GL_VERSION, GL_RENDERER = 0x1F02, 0x1F01
ERROR_CLASS_ALREADY_EXISTS = 1410
CLASS_NAME = "HebrewDictationSkinGL"


class _PIXELFORMATDESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("nSize", w.WORD), ("nVersion", w.WORD), ("dwFlags", w.DWORD),
        ("iPixelType", ctypes.c_ubyte), ("cColorBits", ctypes.c_ubyte),
        ("cRedBits", ctypes.c_ubyte), ("cRedShift", ctypes.c_ubyte),
        ("cGreenBits", ctypes.c_ubyte), ("cGreenShift", ctypes.c_ubyte),
        ("cBlueBits", ctypes.c_ubyte), ("cBlueShift", ctypes.c_ubyte),
        ("cAlphaBits", ctypes.c_ubyte), ("cAlphaShift", ctypes.c_ubyte),
        ("cAccumBits", ctypes.c_ubyte), ("cAccumRedBits", ctypes.c_ubyte),
        ("cAccumGreenBits", ctypes.c_ubyte),
        ("cAccumBlueBits", ctypes.c_ubyte),
        ("cAccumAlphaBits", ctypes.c_ubyte), ("cDepthBits", ctypes.c_ubyte),
        ("cStencilBits", ctypes.c_ubyte), ("cAuxBuffers", ctypes.c_ubyte),
        ("iLayerType", ctypes.c_ubyte), ("bReserved", ctypes.c_ubyte),
        ("dwLayerMask", w.DWORD), ("dwVisibleMask", w.DWORD),
        ("dwDamageMask", w.DWORD)]


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


_proc_ref = None            # Windows calls this; it must outlive us
_registered = False
_local = threading.local()


def _register() -> None:
    global _proc_ref, _registered
    if _registered:
        return
    _proc_ref = _WNDPROC(
        lambda hwnd, msg, wp, lp: _user32.DefWindowProcW(hwnd, msg, wp, lp))
    cls = _WNDCLASS()
    cls.lpfnWndProc = _proc_ref
    cls.lpszClassName = CLASS_NAME
    cls.style = CS_OWNDC             # the DC is kept, so it can stay current
    if not _user32.RegisterClassW(ctypes.byref(cls)):
        err = ctypes.get_last_error()
        if err != ERROR_CLASS_ALREADY_EXISTS:
            raise ctypes.WinError(err)
    _registered = True


class Context:
    """One GL context and one Skia GrDirectContext, owned by one thread."""

    def __init__(self) -> None:
        import skia

        self.hwnd = None
        self.hdc = None
        self.hglrc = None
        self.gr = None
        self.renderer = "?"

        _register()
        # never shown, never sized: it exists only to own a pixel format
        self.hwnd = _user32.CreateWindowExW(
            0, CLASS_NAME, "", WS_POPUP, 0, 0, 8, 8,
            None, None, None, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hdc = _user32.GetDC(self.hwnd)
        if not self.hdc:
            raise RuntimeError("no device context for the GL window")

        pfd = _PIXELFORMATDESCRIPTOR()
        pfd.nSize = ctypes.sizeof(_PIXELFORMATDESCRIPTOR)
        pfd.nVersion = 1
        pfd.dwFlags = PFD_SUPPORT_OPENGL | PFD_DRAW_TO_WINDOW
        pfd.iPixelType = 0                       # PFD_TYPE_RGBA
        pfd.cColorBits = 32
        pfd.cAlphaBits = 8
        pfd.cDepthBits = 24
        pfd.cStencilBits = 8                     # Skia wants a stencil buffer
        fmt = _gdi32.ChoosePixelFormat(self.hdc, ctypes.byref(pfd))
        if not fmt:
            raise RuntimeError("no usable pixel format")
        if not _gdi32.SetPixelFormat(self.hdc, fmt, ctypes.byref(pfd)):
            raise ctypes.WinError(ctypes.get_last_error())

        self.hglrc = _opengl32.wglCreateContext(self.hdc)
        if not self.hglrc:
            raise ctypes.WinError(ctypes.get_last_error())
        if not _opengl32.wglMakeCurrent(self.hdc, self.hglrc):
            raise ctypes.WinError(ctypes.get_last_error())

        name = _opengl32.glGetString(GL_RENDERER)
        self.renderer = (name or b"?").decode("ascii", "replace")
        self.gr = skia.GrDirectContext.MakeGL()
        if self.gr is None:
            raise RuntimeError("Skia would not build a GL context")

    def surface(self, width: int, height: int):
        """A GPU render target. None if the driver refuses one that big."""
        import skia
        try:
            return skia.Surface.MakeRenderTarget(
                self.gr, skia.Budgeted.kNo,
                skia.ImageInfo.MakeN32Premul(int(width), int(height)))
        except Exception:
            _log.debug("skin: no GPU surface at %dx%d", width, height,
                       exc_info=True)
            return None

    def close(self) -> None:
        try:
            if self.gr is not None:
                try:
                    self.gr.abandonContext()
                except Exception:
                    pass
                self.gr = None
            if self.hglrc:
                _opengl32.wglMakeCurrent(None, None)
                _opengl32.wglDeleteContext(self.hglrc)
                self.hglrc = None
            if self.hwnd:
                if self.hdc:
                    _user32.ReleaseDC(self.hwnd, self.hdc)
                    self.hdc = None
                _user32.DestroyWindow(self.hwnd)
                self.hwnd = None
        except Exception:
            _log.debug("skin: GL teardown", exc_info=True)


def acquire() -> "Context | None":
    """This thread's GL context, built on first ask. None if unavailable.

    Cached per thread INCLUDING the failure, so a machine with no usable
    GPU pays the ~270 ms probe once rather than on every window.
    """
    got = getattr(_local, "ctx", "missing")
    if got != "missing":
        return got
    ctx = None
    try:
        ctx = Context()
        _log.info("skin: drawing on the GPU (%s)", ctx.renderer)
    except Exception as e:
        _log.info("skin: no GPU context, falling back to CPU raster (%r)", e)
        ctx = None
    _local.ctx = ctx
    return ctx


def release() -> None:
    """Drop this thread's context. Called from the thread that made it."""
    ctx = getattr(_local, "ctx", None)
    if ctx is not None:
        ctx.close()
    _local.ctx = "missing"
