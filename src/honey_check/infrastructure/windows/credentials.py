"""Administrador de credenciales de Windows: listar y eliminar sin leer nunca el secreto."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class _Credential(ctypes.Structure):
    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.c_void_p),  # nunca se lee
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.CredEnumerateW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_Credential))),
)
_advapi32.CredEnumerateW.restype = wintypes.BOOL
_advapi32.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
_advapi32.CredDeleteW.restype = wintypes.BOOL
_advapi32.CredFree.argtypes = (ctypes.c_void_p,)

TYPES = {
    1: "Genérica",
    2: "Contraseña de Windows",
    3: "Certificado de Windows",
    4: "Contraseña visible",
    5: "Certificado genérico",
    6: "Credencial extendida",
}
PERSIST = {1: "Solo esta sesión", 2: "Este equipo", 3: "Perfil móvil"}
_ERROR_NOT_FOUND = 1168


@dataclass(frozen=True)
class StoredCredential:
    target: str
    type: int
    user: str | None
    persist: int
    last_written: datetime | None
    comment: str | None


def _filetime(value: wintypes.FILETIME) -> datetime | None:
    ticks = (value.dwHighDateTime << 32) | value.dwLowDateTime
    return datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10) if ticks else None


def list_credentials() -> list[StoredCredential]:
    count = wintypes.DWORD()
    items = ctypes.POINTER(ctypes.POINTER(_Credential))()
    if not _advapi32.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(items)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return []
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = []
        for index in range(count.value):
            item = items[index].contents
            result.append(
                StoredCredential(
                    target=item.TargetName or "",
                    type=int(item.Type),
                    user=item.UserName,
                    persist=int(item.Persist),
                    last_written=_filetime(item.LastWritten),
                    comment=item.Comment,
                )
            )
        return result
    finally:
        _advapi32.CredFree(items)


def delete_credential(target: str, type_: int) -> bool:
    if _advapi32.CredDeleteW(target, type_, 0):
        return True
    if ctypes.get_last_error() == _ERROR_NOT_FOUND:
        return False
    raise ctypes.WinError(ctypes.get_last_error())
