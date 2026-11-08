"""Permisos de administrador: saber si el proceso está elevado y relanzarlo con el aviso UAC.

Honey Check no ve ni guarda credenciales: Windows las pide en su propio diálogo seguro y la sesión
elevada dura hasta que se cierra el programa.
"""

from __future__ import annotations

import ctypes
import subprocess
from collections.abc import Sequence
from ctypes import wintypes

_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100
_SW_HIDE = 0
_ERROR_CANCELLED = 1223
_WAIT_OBJECT_0 = 0

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_advapi32.OpenProcessToken.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
)
_advapi32.GetTokenInformation.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    )


_shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
_shell32.ShellExecuteExW.restype = wintypes.BOOL


class ElevationCancelled(Exception):
    """El técnico cerró o rechazó el aviso de Control de cuentas."""


def is_elevated() -> bool | None:
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(
        _kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        return None
    try:
        elevation = wintypes.DWORD()
        size = wintypes.DWORD()
        if not _advapi32.GetTokenInformation(
            token,
            _TOKEN_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(size),
        ):
            return None
        return bool(elevation.value)
    finally:
        _kernel32.CloseHandle(token)


class ElevatedProcess:
    """El proceso elevado recién lanzado; permite saber si terminó antes de tiempo."""

    def __init__(self, handle: int) -> None:
        self._handle = handle

    def has_exited(self) -> bool:
        return bool(_kernel32.WaitForSingleObject(self._handle, 0) == _WAIT_OBJECT_0)

    def close(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = 0


def launch_elevated(executable: str, arguments: Sequence[str], directory: str) -> ElevatedProcess:
    """Bloquea hasta que el técnico responde el aviso UAC."""
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = subprocess.list2cmdline(list(arguments))
    info.lpDirectory = directory
    info.nShow = _SW_HIDE
    if not _shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == _ERROR_CANCELLED:
            raise ElevationCancelled
        raise ctypes.WinError(error)
    return ElevatedProcess(info.hProcess or 0)
