"""Iconos de programas como PNG pequeños, sin dependencias: Win32 para leer y zlib para codificar.

Solo lee: `ExtractIconExW` obtiene el icono del recurso del ejecutable, igual que el Explorador.
"""

from __future__ import annotations

import ctypes
import logging
import ntpath
import os
import re
import struct
import zlib
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

ICON_SIZE = 32
MAX_LOGO_BYTES = 256 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_DIB_RGB_COLORS = 0
_BI_RGB = 0


class _IconInfo(ctypes.Structure):
    _fields_ = (
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    )


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.ExtractIconExW.argtypes = (
    wintypes.LPCWSTR,
    ctypes.c_int,
    ctypes.POINTER(wintypes.HICON),
    ctypes.POINTER(wintypes.HICON),
    wintypes.UINT,
)
_shell32.ExtractIconExW.restype = wintypes.UINT
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetIconInfo.argtypes = (wintypes.HICON, ctypes.POINTER(_IconInfo))
_user32.DestroyIcon.argtypes = (wintypes.HICON,)
_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi32.GetDIBits.argtypes = (
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
)
_gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """PNG RGBA de 8 bits por canal, sin filtros."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _bitmap_pixels(dc: int, bitmap: int, size: int) -> bytes | None:
    header = _BitmapInfoHeader(
        biSize=ctypes.sizeof(_BitmapInfoHeader),
        biWidth=size,
        biHeight=-size,  # de arriba abajo
        biPlanes=1,
        biBitCount=32,
        biCompression=_BI_RGB,
    )
    buffer = ctypes.create_string_buffer(size * size * 4)
    lines = _gdi32.GetDIBits(dc, bitmap, 0, size, buffer, ctypes.byref(header), _DIB_RGB_COLORS)
    return buffer.raw if lines == size else None


def _icon_to_png(icon: int) -> bytes | None:
    info = _IconInfo()
    if not _user32.GetIconInfo(icon, ctypes.byref(info)):
        return None
    dc = _user32.GetDC(None)
    try:
        if not info.hbmColor:
            return None  # Icono monocromo: no merece la pena representarlo.
        bgra = _bitmap_pixels(dc, info.hbmColor, ICON_SIZE)
        if bgra is None:
            return None
        has_alpha = any(bgra[i] for i in range(3, len(bgra), 4))
        mask = None if has_alpha else _bitmap_pixels(dc, info.hbmMask, ICON_SIZE)
        rgba = bytearray(len(bgra))
        for i in range(0, len(bgra), 4):
            blue, green, red, alpha = bgra[i], bgra[i + 1], bgra[i + 2], bgra[i + 3]
            if not has_alpha:
                # Iconos antiguos sin alfa: la máscara indica qué píxeles son transparentes.
                alpha = 0 if mask is not None and mask[i] else 255
            rgba[i : i + 4] = bytes((red, green, blue, alpha))
        if not any(rgba[i] for i in range(3, len(rgba), 4)):
            return None
        return encode_png(ICON_SIZE, ICON_SIZE, bytes(rgba))
    finally:
        _user32.ReleaseDC(None, dc)
        if info.hbmColor:
            _gdi32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            _gdi32.DeleteObject(info.hbmMask)


class WinIconExtractor:
    """Implementa IconExtractor. Cualquier fallo significa «sin icono», nunca un error."""

    def executable_icon(self, path: str) -> bytes | None:
        large = wintypes.HICON()
        try:
            count = _shell32.ExtractIconExW(path, 0, ctypes.byref(large), None, 1)
        except OSError:
            return None
        if not count or not large.value:
            return None
        try:
            return _icon_to_png(large.value)
        except OSError:
            return None
        finally:
            _user32.DestroyIcon(large)

    def package_logo(self, install_location: str, logo: str) -> bytes | None:
        """El manifiesto declara `Assets\\Logo.png`, pero en disco hay variantes por escala."""
        relative = ntpath.normpath(logo)
        if relative.startswith("..") or ntpath.isabs(relative):
            return None
        folder = ntpath.join(install_location, ntpath.dirname(relative))
        stem, extension = ntpath.splitext(ntpath.basename(relative))
        pattern = re.compile(
            rf"^{re.escape(stem)}(\.(scale|targetsize)-\d+(_altform-\w+)?)?{re.escape(extension)}$",
            re.IGNORECASE,
        )
        try:
            names = [e.name for e in os.scandir(folder) if pattern.match(e.name)]
        except OSError:
            return None
        # Preferimos la variante de escala 100 o la más pequeña: es la que se muestra a 32 px.
        names.sort(key=lambda n: (0 if "scale-100" in n.lower() else 1, len(n)))
        for name in names[:4]:
            path = Path(folder, name)
            try:
                if path.stat().st_size > MAX_LOGO_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if data.startswith(_PNG_SIGNATURE):
                return data
        return None
