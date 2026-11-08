"""Usuario de la sesión: SID y carpetas de su perfil, para pasarlos a un proceso elevado."""

from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

from honey_check.application.support.ports import UserSession

_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_FOLDERID_DESKTOP = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_ole32 = ctypes.WinDLL("ole32")

_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
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
_advapi32.ConvertSidToStringSidW.argtypes = (wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR))
_shell32.SHGetKnownFolderPath.argtypes = (
    ctypes.c_char_p,
    wintypes.DWORD,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.LPWSTR),
)
_ole32.CoTaskMemFree.argtypes = (wintypes.LPVOID,)


def current_user_sid() -> str | None:
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(
        _kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        return None
    try:
        size = wintypes.DWORD()
        _advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not _advapi32.GetTokenInformation(token, _TOKEN_USER, buffer, size, ctypes.byref(size)):
            return None
        # TOKEN_USER empieza con SID_AND_ATTRIBUTES: el primer campo es el puntero al SID.
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(wintypes.LPVOID))[0]
        text = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            return None
        try:
            return text.value
        finally:
            _kernel32.LocalFree(ctypes.cast(text, wintypes.HLOCAL))
    finally:
        _kernel32.CloseHandle(token)


def _known_folder(folder: uuid.UUID) -> str | None:
    path = wintypes.LPWSTR()
    if _shell32.SHGetKnownFolderPath(folder.bytes_le, 0, None, ctypes.byref(path)) != 0:
        return None
    try:
        return path.value
    finally:
        _ole32.CoTaskMemFree(path)


def current_session() -> UserSession | None:
    sid = current_user_sid()
    profile = os.environ.get("USERPROFILE")
    if not sid or not profile:
        return None
    home = Path(profile)
    return UserSession(
        sid=sid,
        profile=profile,
        appdata=os.environ.get("APPDATA") or str(home / "AppData" / "Roaming"),
        local_appdata=os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local"),
        desktop=_known_folder(_FOLDERID_DESKTOP) or str(home / "Desktop"),
    )


def user_registry_key(short: str, session: UserSession | None) -> str:
    """HKCU del usuario de la sesión: en un proceso elevado de otro usuario, HKU\\<SID>."""
    head, _, rest = short.partition("\\")
    if head.upper() not in ("HKCU", "HKEY_CURRENT_USER") or session is None:
        return short
    if current_user_sid() == session.sid:
        return short
    return f"HKU\\{session.sid}\\{rest}" if rest else f"HKU\\{session.sid}"
