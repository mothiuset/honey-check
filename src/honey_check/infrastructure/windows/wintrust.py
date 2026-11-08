"""Verificación Authenticode en el propio proceso con WinVerifyTrust, sin tocar la red.

`Get-AuthenticodeSignature` intentaba comprobar revocación y tardaba más de un segundo por archivo
en un equipo sin internet. Aquí la revocación se desactiva y la descarga de URL queda limitada a la
caché local: el resultado indica si la firma es válida y de confianza, no si fue revocada después.
Los archivos firmados por catálogo (muchos binarios de Windows) se verifican también por catálogo.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from ctypes import wintypes

from honey_check.application.ports import CancelToken, SignatureResult

from .crypt32 import signer_of

log = logging.getLogger(__name__)

_WTD_UI_NONE = 2
_WTD_REVOKE_NONE = 0
_WTD_CHOICE_FILE = 1
_WTD_CHOICE_CATALOG = 2
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_WTD_CACHE_ONLY_URL_RETRIEVAL = 0x1000
_WTD_REVOCATION_CHECK_NONE = 0x10
_FLAGS = _WTD_CACHE_ONLY_URL_RETRIEVAL | _WTD_REVOCATION_CHECK_NONE

_TRUST_E_NOSIGNATURE = 0x800B0100
_TRUST_E_SUBJECT_FORM_UNKNOWN = 0x800B0003
_TRUST_E_PROVIDER_UNKNOWN = 0x800B0001
_TRUST_E_BAD_DIGEST = 0x80096010
_CERT_E_UNTRUSTEDROOT = 0x800B0109
_CERT_E_CHAINING = 0x800B010A
_TRUST_E_EXPLICIT_DISTRUST = 0x800B0111
_CERT_E_EXPIRED = 0x800B0101
_CRYPT_E_FILE_ERROR = 0x80092003

_MAX_WORKERS = max(2, min(8, os.cpu_count() or 4))
_MAX_FILE_BYTES = 512 * 1024 * 1024


class _Guid(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )


# WINTRUST_ACTION_GENERIC_VERIFY_V2 {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}
_ACTION_VERIFY_V2 = _Guid(
    0x00AAC56B, 0xCD44, 0x11D0, (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE)
)


class _FileInfo(ctypes.Structure):
    _fields_ = (
        ("cbStruct", wintypes.DWORD),
        ("pcwszFilePath", wintypes.LPCWSTR),
        ("hFile", wintypes.HANDLE),
        ("pgKnownSubject", ctypes.c_void_p),
    )


class _CatalogInfo(ctypes.Structure):
    _fields_ = (
        ("cbStruct", wintypes.DWORD),
        ("dwCatalogVersion", wintypes.DWORD),
        ("pcwszCatalogFilePath", wintypes.LPCWSTR),
        ("pcwszMemberTag", wintypes.LPCWSTR),
        ("pcwszMemberFilePath", wintypes.LPCWSTR),
        ("hMemberFile", wintypes.HANDLE),
        ("pbCalculatedFileHash", ctypes.c_void_p),
        ("cbCalculatedFileHash", wintypes.DWORD),
        ("pcCatalogContext", ctypes.c_void_p),
        ("hCatAdmin", wintypes.HANDLE),
    )


class _TrustData(ctypes.Structure):
    _fields_ = (
        ("cbStruct", wintypes.DWORD),
        ("pPolicyCallbackData", ctypes.c_void_p),
        ("pSIPClientData", ctypes.c_void_p),
        ("dwUIChoice", wintypes.DWORD),
        ("fdwRevocationChecks", wintypes.DWORD),
        ("dwUnionChoice", wintypes.DWORD),
        ("pInfo", ctypes.c_void_p),
        ("dwStateAction", wintypes.DWORD),
        ("hWVTStateData", wintypes.HANDLE),
        ("pwszURLReference", wintypes.LPCWSTR),
        ("dwProvFlags", wintypes.DWORD),
        ("dwUIContext", wintypes.DWORD),
        ("pSignatureSettings", ctypes.c_void_p),
    )


_wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
_wintrust.WinVerifyTrust.argtypes = (wintypes.HWND, ctypes.POINTER(_Guid), ctypes.c_void_p)
_wintrust.WinVerifyTrust.restype = ctypes.c_long
_wintrust.CryptCATAdminAcquireContext2.argtypes = (
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(_Guid),
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_wintrust.CryptCATAdminAcquireContext2.restype = wintypes.BOOL
_wintrust.CryptCATAdminCalcHashFromFileHandle2.argtypes = (
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
    wintypes.DWORD,
)
_wintrust.CryptCATAdminCalcHashFromFileHandle2.restype = wintypes.BOOL
_wintrust.CryptCATAdminEnumCatalogFromHash.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
)
_wintrust.CryptCATAdminEnumCatalogFromHash.restype = wintypes.HANDLE
_wintrust.CryptCATAdminReleaseCatalogContext.argtypes = (
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.DWORD,
)
_wintrust.CryptCATAdminReleaseContext.argtypes = (wintypes.HANDLE, wintypes.DWORD)


class _CatalogInfoQuery(ctypes.Structure):
    _fields_ = (("cbStruct", wintypes.DWORD), ("wszCatalogFile", wintypes.WCHAR * 260))


_wintrust.CryptCATCatalogInfoFromContext.argtypes = (
    wintypes.HANDLE,
    ctypes.POINTER(_CatalogInfoQuery),
    wintypes.DWORD,
)
_wintrust.CryptCATCatalogInfoFromContext.restype = wintypes.BOOL

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateFileW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ_WRITE_DELETE = 0x7
_OPEN_EXISTING = 3

_BCRYPT_SHA256 = "SHA256"


def _status_for(code: int) -> str:
    unsigned = code & 0xFFFFFFFF
    if unsigned == 0:
        return "valid"
    if unsigned in (_TRUST_E_NOSIGNATURE, _TRUST_E_SUBJECT_FORM_UNKNOWN, _TRUST_E_PROVIDER_UNKNOWN):
        return "not_signed"
    if unsigned == _TRUST_E_BAD_DIGEST:
        return "hash_mismatch"
    if unsigned in (_CERT_E_UNTRUSTEDROOT, _CERT_E_CHAINING, _TRUST_E_EXPLICIT_DISTRUST):
        return "not_trusted"
    if unsigned == _CERT_E_EXPIRED:
        return "not_trusted"
    return "unknown_error"


def _verify(data: _TrustData) -> int:
    data.dwStateAction = _WTD_STATEACTION_VERIFY
    result = _wintrust.WinVerifyTrust(None, ctypes.byref(_ACTION_VERIFY_V2), ctypes.byref(data))
    data.dwStateAction = _WTD_STATEACTION_CLOSE
    _wintrust.WinVerifyTrust(None, ctypes.byref(_ACTION_VERIFY_V2), ctypes.byref(data))
    return int(result)


def _base_trust_data(choice: int, info: ctypes.Structure) -> _TrustData:
    return _TrustData(
        cbStruct=ctypes.sizeof(_TrustData),
        dwUIChoice=_WTD_UI_NONE,
        fdwRevocationChecks=_WTD_REVOKE_NONE,
        dwUnionChoice=choice,
        pInfo=ctypes.cast(ctypes.pointer(info), ctypes.c_void_p),
        dwProvFlags=_FLAGS,
    )


def verify_embedded(path: str) -> int:
    info = _FileInfo(cbStruct=ctypes.sizeof(_FileInfo), pcwszFilePath=path)
    return _verify(_base_trust_data(_WTD_CHOICE_FILE, info))


def verify_catalog(path: str) -> int | None:
    """Devuelve el resultado por catálogo, o None si el archivo no figura en ningún catálogo."""
    admin = wintypes.HANDLE()
    if not _wintrust.CryptCATAdminAcquireContext2(
        ctypes.byref(admin), None, _BCRYPT_SHA256, None, 0
    ):
        return None
    handle = _kernel32.CreateFileW(
        path, _GENERIC_READ, _FILE_SHARE_READ_WRITE_DELETE, None, _OPEN_EXISTING, 0, None
    )
    if not handle or handle == _INVALID_HANDLE:
        _wintrust.CryptCATAdminReleaseContext(admin, 0)
        return None
    catalog = wintypes.HANDLE()
    try:
        size = wintypes.DWORD(0)
        _wintrust.CryptCATAdminCalcHashFromFileHandle2(admin, handle, ctypes.byref(size), None, 0)
        if not size.value:
            return None
        digest = (ctypes.c_ubyte * size.value)()
        if not _wintrust.CryptCATAdminCalcHashFromFileHandle2(
            admin, handle, ctypes.byref(size), digest, 0
        ):
            return None
        catalog = _wintrust.CryptCATAdminEnumCatalogFromHash(admin, digest, size, 0, None)
        if not catalog:
            return None
        query = _CatalogInfoQuery(cbStruct=ctypes.sizeof(_CatalogInfoQuery))
        if not _wintrust.CryptCATCatalogInfoFromContext(catalog, ctypes.byref(query), 0):
            return None
        tag = "".join(f"{byte:02X}" for byte in digest)
        info = _CatalogInfo(
            cbStruct=ctypes.sizeof(_CatalogInfo),
            pcwszCatalogFilePath=query.wszCatalogFile,
            pcwszMemberTag=tag,
            pcwszMemberFilePath=path,
            hMemberFile=handle,
            pbCalculatedFileHash=ctypes.cast(digest, ctypes.c_void_p),
            cbCalculatedFileHash=size.value,
            hCatAdmin=admin,
        )
        return _verify(_base_trust_data(_WTD_CHOICE_CATALOG, info))
    finally:
        if catalog:
            _wintrust.CryptCATAdminReleaseCatalogContext(admin, catalog, 0)
        _kernel32.CloseHandle(handle)
        _wintrust.CryptCATAdminReleaseContext(admin, 0)


def check_signature(path: str) -> SignatureResult:
    try:
        if os.path.getsize(path) > _MAX_FILE_BYTES:  # noqa: PTH202
            return SignatureResult("unknown_error")
    except OSError:
        return SignatureResult("unknown_error")
    status = _status_for(verify_embedded(path))
    if status == "not_signed":
        catalog = verify_catalog(path)
        if catalog is not None:
            # Firmado por un catálogo de Windows: el firmante es el del catálogo, no el archivo.
            return SignatureResult(_status_for(catalog), "Catálogo de Windows")
        return SignatureResult(status)
    return SignatureResult(status, signer_of(path))


class WinTrustSignatures:
    """Implementa SignatureInspector: varios archivos a la vez, con presupuesto de tiempo."""

    def inspect(
        self, paths: Sequence[str], cancel: CancelToken, timeout_s: float
    ) -> dict[str, SignatureResult]:
        found: dict[str, SignatureResult] = {}
        lock = threading.Lock()
        deadline = time.monotonic() + timeout_s

        def work(path: str) -> None:
            if cancel.cancelled or time.monotonic() >= deadline:
                return
            result = check_signature(path)
            with lock:
                found[path] = result

        # Hilos en lugar de procesos: WinVerifyTrust es seguro entre hilos y no hay arranques.
        executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="wintrust")
        futures = [executor.submit(work, path) for path in paths]
        wait(futures, timeout=max(0.0, deadline - time.monotonic()))
        # Lo que no terminó se abandona; no se espera a ningún archivo colgado.
        executor.shutdown(wait=False, cancel_futures=True)
        with lock:
            return dict(found)
