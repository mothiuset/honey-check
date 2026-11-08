"""Inspección acotada de archivos: estado de rutas, metadatos de versión y cabecera PE."""

from __future__ import annotations

import ctypes
import logging
import os
import struct
from ctypes import wintypes
from pathlib import Path

from honey_check.application.ports import FileMetadata
from honey_check.domain.inventory import PathState

log = logging.getLogger(__name__)

_DRIVE_REMOTE = 4
_DRIVE_NO_ROOT = 1
_DOS_HEADER_BYTES = 64
_PE_MACHINES = {
    0x014C: "x86",
    0x8664: "x64",
    0xAA64: "arm64",
    0x01C4: "arm",
}

_version = ctypes.WinDLL("version", use_last_error=True)
_version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, wintypes.LPDWORD)
_version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_version.GetFileVersionInfoW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
)
_version.GetFileVersionInfoW.restype = wintypes.BOOL
_version.VerQueryValueW.argtypes = (
    wintypes.LPCVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(wintypes.LPVOID),
    ctypes.POINTER(wintypes.UINT),
)
_version.VerQueryValueW.restype = wintypes.BOOL
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetDriveTypeW.restype = wintypes.UINT


def is_network_path(path: str) -> bool:
    """Las rutas de red pueden bloquear durante minutos: nunca se tocan durante el inventario."""
    if path.startswith(("\\\\", "//")):
        return True
    drive = os.path.splitdrive(path)[0]
    if not drive:
        return True
    return int(_kernel32.GetDriveTypeW(drive + "\\")) == _DRIVE_REMOTE


def _drive_missing(path: str) -> bool:
    drive = os.path.splitdrive(path)[0]
    return int(_kernel32.GetDriveTypeW(drive + "\\")) == _DRIVE_NO_ROOT


def _query_string(block: ctypes.Array[ctypes.c_char], sub_block: str) -> str | None:
    pointer = wintypes.LPVOID()
    length = wintypes.UINT()
    if not _version.VerQueryValueW(block, sub_block, ctypes.byref(pointer), ctypes.byref(length)):
        return None
    if not pointer.value or not length.value:
        return None
    text = ctypes.wstring_at(pointer.value, length.value).rstrip("\x00").strip()
    return text or None


def _read_version_strings(path: str) -> dict[str, str | None]:
    handle = wintypes.DWORD()
    size = _version.GetFileVersionInfoSizeW(path, ctypes.byref(handle))
    if not size:
        return {}
    block = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(path, 0, size, block):
        return {}

    pointer = wintypes.LPVOID()
    length = wintypes.UINT()
    translations: list[tuple[int, int]] = []
    if (
        _version.VerQueryValueW(
            block, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)
        )
        and pointer.value
    ):
        raw = ctypes.string_at(pointer.value, length.value)
        for offset in range(0, len(raw) - 3, 4):
            translations.append(struct.unpack_from("<HH", raw, offset))
    translations.extend([(0x0409, 0x04B0), (0x0409, 0x04E4), (0, 0x04B0)])

    wanted = ("FileVersion", "ProductVersion", "ProductName", "FileDescription", "CompanyName")
    found: dict[str, str | None] = {}
    for language, codepage in translations:
        for name in wanted:
            if found.get(name):
                continue
            found[name] = _query_string(
                block, rf"\StringFileInfo\{language:04x}{codepage:04x}\{name}"
            )
        if all(found.get(name) for name in wanted):
            break
    return found


def read_pe_machine(path: str) -> str | None:
    """Arquitectura según la cabecera PE. Solo lee los primeros bytes del archivo."""
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(_DOS_HEADER_BYTES)
            if len(header) < _DOS_HEADER_BYTES or header[:2] != b"MZ":
                return None
            offset = struct.unpack_from("<I", header, 0x3C)[0]
            if offset > 1024 * 1024:
                return None
            handle.seek(offset)
            signature = handle.read(6)
    except OSError:
        return None
    if len(signature) < 6 or signature[:4] != b"PE\x00\x00":
        return None
    return _PE_MACHINES.get(struct.unpack_from("<H", signature, 4)[0])


class WinFileInspector:
    def path_state(self, path: str) -> PathState:
        if is_network_path(path):
            return PathState.NOT_CHECKED
        if _drive_missing(path):
            return PathState.MISSING
        try:
            os.stat(path)  # noqa: PTH116 - se distingue «no existe» de «sin permisos»
        except FileNotFoundError:
            return PathState.MISSING
        except NotADirectoryError:
            return PathState.MISSING
        except PermissionError:
            return PathState.INACCESSIBLE
        except OSError:
            return PathState.INACCESSIBLE
        return PathState.VALID

    def list_executables(self, directory: str, limit: int) -> list[str]:
        if is_network_path(directory):
            return []
        found: list[str] = []
        try:
            with os.scandir(directory) as entries:
                for inspected, entry in enumerate(entries):
                    if inspected >= limit:
                        break
                    if entry.name.lower().endswith(".exe") and entry.is_file():
                        found.append(entry.path)
        except OSError:
            return []
        return found

    def metadata(self, path: str) -> FileMetadata:
        if is_network_path(path):
            return FileMetadata()
        try:
            strings = _read_version_strings(path)
        except OSError:
            strings = {}
        return FileMetadata(
            file_version=strings.get("FileVersion"),
            product_version=strings.get("ProductVersion"),
            product_name=strings.get("ProductName"),
            file_description=strings.get("FileDescription"),
            company_name=strings.get("CompanyName"),
            machine=read_pe_machine(path),
        )

    def read_text(self, path: str, max_bytes: int) -> str | None:
        if is_network_path(path):
            return None
        try:
            with Path(path).open("rb") as handle:
                data = handle.read(max_bytes + 1)
        except OSError:
            return None
        if len(data) > max_bytes:
            return None
        for encoding in ("utf-8-sig", "utf-16"):
            try:
                return data.decode(encoding)
            except UnicodeError:
                continue
        return None
