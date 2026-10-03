"""The icon Windows' own shell resolves for a thing, saved as a PNG.

    python shell_icon.py <parsing name> <size> <out.png>

`parsing name` is anything the shell can parse: an installed package's
application (`shell:AppsFolder\\<family>!<app id>` — what the taskbar,
Start and Alt+Tab draw), a shortcut's path, a file. store.yml runs it on
the smoke install so the logo can be LOOKED AT as Windows resolves it —
through resources.pri, the targetsize and unplated names (assets.py) —
rather than inferred from the package's files, and so that a picture of
the taskbar that is late to load its icons is not the only evidence.

IShellItemImageFactory::GetImage with SIIGBF_ICONONLY, read back with
GetDIBits as 32-bit top-down BGRA (premultiplied, as the shell hands it
over). ctypes only: this runs under the package tree's own Python, which
has Pillow and nothing else.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as w

from PIL import Image, ImageStat

SIIGBF_ICONONLY = 0x04
DIB_RGB_COLORS = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", w.WORD), ("bmBitsPixel", w.WORD),
                ("bmBits", ctypes.c_void_p)]


def shell_icon(name: str, size: int) -> Image.Image:
    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    gdi32 = ctypes.WinDLL("gdi32")
    user32 = ctypes.WinDLL("user32")
    ole32.CoInitialize(None)
    iid = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p("{bcc18b79-ba16-442f-80c4-8a59c30c463b}"),
                          ctypes.byref(iid))
    factory = ctypes.c_void_p()
    shell32.SHCreateItemFromParsingName.argtypes = [
        ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p)]
    hr = shell32.SHCreateItemFromParsingName(name, None, ctypes.byref(iid),
                                             ctypes.byref(factory))
    if hr != 0 or not factory:
        raise OSError(f"SHCreateItemFromParsingName({name!r}) failed: 0x{hr & 0xFFFFFFFF:08x}")
    vtable = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0],
                         ctypes.POINTER(ctypes.c_void_p))
    get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_void_p))(vtable[3])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    bitmap = ctypes.c_void_p()
    try:
        hr = get_image(factory, SIZE(size, size), SIIGBF_ICONONLY, ctypes.byref(bitmap))
        if hr != 0 or not bitmap:
            raise OSError(f"GetImage({name!r}, {size}) failed: 0x{hr & 0xFFFFFFFF:08x}")
        gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        info = BITMAP()
        gdi32.GetObjectW(bitmap, ctypes.sizeof(info), ctypes.byref(info))
        width, height = info.bmWidth, abs(info.bmHeight)
        header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width,
                                  biHeight=-height, biPlanes=1, biBitCount=32)
        pixels = ctypes.create_string_buffer(width * height * 4)
        user32.GetDC.restype = ctypes.c_void_p
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_uint]
        dc = user32.GetDC(None)
        try:
            lines = gdi32.GetDIBits(dc, bitmap, 0, height, pixels, ctypes.byref(header),
                                    DIB_RGB_COLORS)
        finally:
            user32.ReleaseDC(None, dc)
        if lines != height:
            raise OSError(f"GetDIBits read {lines} of {height} lines")
        return Image.frombuffer("RGBA", (width, height), pixels.raw, "raw", "BGRA", 0, 1)
    finally:
        if bitmap:
            gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
            gdi32.DeleteObject(bitmap)
        release(factory)


def main(argv: list[str]) -> int:
    name, size, out = argv[0], int(argv[1]), argv[2]
    picture = shell_icon(name, size)
    picture.save(out)
    solid = picture.getchannel("A").point(lambda v: 255 if v > 200 else 0)
    count = solid.histogram()[255]
    mean = tuple(round(c) for c in ImageStat.Stat(picture.convert("RGB"), mask=solid).mean) \
        if count else None
    print(f"{name} at {size}: {picture.size}, {count} opaque pixels, mean colour {mean}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
