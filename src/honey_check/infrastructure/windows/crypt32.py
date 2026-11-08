"""Lectura de certificados con crypt32: firmante de un ejecutable y almacenes del sistema."""

from __future__ import annotations

import ctypes
import hashlib
from collections.abc import Iterator
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_CERT_QUERY_OBJECT_FILE = 1
_CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED = 1 << 10
_CERT_QUERY_FORMAT_FLAG_BINARY = 1 << 1
_CMSG_SIGNER_INFO_PARAM = 6
_ENCODING = 0x00000001 | 0x00010000  # X509_ASN_ENCODING | PKCS_7_ASN_ENCODING
_CERT_FIND_SUBJECT_CERT = 0x000B0000
_CERT_NAME_SIMPLE_DISPLAY_TYPE = 4
_CERT_NAME_ISSUER_FLAG = 0x1
_CERT_KEY_PROV_INFO_PROP_ID = 2
_CERT_SHA1_HASH_PROP_ID = 3
_CERT_FRIENDLY_NAME_PROP_ID = 11

_CERT_STORE_PROV_SYSTEM_W = ctypes.c_void_p(10)
_CERT_SYSTEM_STORE_CURRENT_USER = 1 << 16
_CERT_SYSTEM_STORE_LOCAL_MACHINE = 2 << 16
_CERT_STORE_READONLY_FLAG = 0x00008000
_CERT_STORE_OPEN_EXISTING_FLAG = 0x00004000
_CERT_STORE_MAXIMUM_ALLOWED_FLAG = 0x00001000
_CERT_STORE_DELETE_FLAG = 0x10

_WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


class _Blob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte)))


class _AlgorithmId(ctypes.Structure):
    _fields_ = (("pszObjId", ctypes.c_char_p), ("Parameters", _Blob))


class _BitBlob(ctypes.Structure):
    _fields_ = (
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ("cUnusedBits", wintypes.DWORD),
    )


class _PublicKeyInfo(ctypes.Structure):
    _fields_ = (("Algorithm", _AlgorithmId), ("PublicKey", _BitBlob))


class _CertInfo(ctypes.Structure):
    _fields_ = (
        ("dwVersion", wintypes.DWORD),
        ("SerialNumber", _Blob),
        ("SignatureAlgorithm", _AlgorithmId),
        ("Issuer", _Blob),
        ("NotBefore", wintypes.FILETIME),
        ("NotAfter", wintypes.FILETIME),
        ("Subject", _Blob),
        ("SubjectPublicKeyInfo", _PublicKeyInfo),
        ("IssuerUniqueId", _BitBlob),
        ("SubjectUniqueId", _BitBlob),
        ("cExtension", wintypes.DWORD),
        ("rgExtension", ctypes.c_void_p),
    )


class _CertContext(ctypes.Structure):
    _fields_ = (
        ("dwCertEncodingType", wintypes.DWORD),
        ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbCertEncoded", wintypes.DWORD),
        ("pCertInfo", ctypes.POINTER(_CertInfo)),
        ("hCertStore", wintypes.HANDLE),
    )


class _SignerInfoPrefix(ctypes.Structure):
    """Solo los campos iniciales de CMSG_SIGNER_INFO, los que identifican al firmante."""

    _fields_ = (("dwVersion", wintypes.DWORD), ("Issuer", _Blob), ("SerialNumber", _Blob))


class _KeyProvInfo(ctypes.Structure):
    _fields_ = (
        ("pwszContainerName", wintypes.LPWSTR),
        ("pwszProvName", wintypes.LPWSTR),
        ("dwProvType", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("cProvParam", wintypes.DWORD),
        ("rgProvParam", ctypes.c_void_p),
        ("dwKeySpec", wintypes.DWORD),
    )


_PCCERT = ctypes.POINTER(_CertContext)
_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_crypt32.CryptQueryObject.argtypes = (
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.c_void_p,
)
_crypt32.CryptQueryObject.restype = wintypes.BOOL
_crypt32.CryptMsgGetParam.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
)
_crypt32.CryptMsgGetParam.restype = wintypes.BOOL
_crypt32.CryptMsgClose.argtypes = (wintypes.HANDLE,)
_crypt32.CertFindCertificateInStore.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    _PCCERT,
)
_crypt32.CertFindCertificateInStore.restype = _PCCERT
_crypt32.CertGetNameStringW.argtypes = (
    _PCCERT,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.LPWSTR,
    wintypes.DWORD,
)
_crypt32.CertGetNameStringW.restype = wintypes.DWORD
_crypt32.CertFreeCertificateContext.argtypes = (_PCCERT,)
_crypt32.CertDuplicateCertificateContext.argtypes = (_PCCERT,)
_crypt32.CertDuplicateCertificateContext.restype = _PCCERT
_crypt32.CertCloseStore.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_crypt32.CertOpenStore.argtypes = (
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_void_p,
)
_crypt32.CertOpenStore.restype = wintypes.HANDLE
_crypt32.CertEnumCertificatesInStore.argtypes = (wintypes.HANDLE, _PCCERT)
_crypt32.CertEnumCertificatesInStore.restype = _PCCERT
_crypt32.CertGetCertificateContextProperty.argtypes = (
    _PCCERT,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
)
_crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
_crypt32.CertDeleteCertificateFromStore.argtypes = (_PCCERT,)
_crypt32.CertDeleteCertificateFromStore.restype = wintypes.BOOL


def _name(context: Any, issuer: bool = False) -> str | None:
    flags = _CERT_NAME_ISSUER_FLAG if issuer else 0
    size = _crypt32.CertGetNameStringW(
        context, _CERT_NAME_SIMPLE_DISPLAY_TYPE, flags, None, None, 0
    )
    if size <= 1:
        return None
    buffer = ctypes.create_unicode_buffer(size)
    _crypt32.CertGetNameStringW(context, _CERT_NAME_SIMPLE_DISPLAY_TYPE, flags, None, buffer, size)
    return buffer.value or None


def signer_of(path: str) -> str | None:
    """Nombre del firmante de una firma Authenticode incrustada; None si no la hay."""
    store = wintypes.HANDLE()
    message = wintypes.HANDLE()
    if not _crypt32.CryptQueryObject(
        _CERT_QUERY_OBJECT_FILE,
        ctypes.c_wchar_p(path),
        _CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED,
        _CERT_QUERY_FORMAT_FLAG_BINARY,
        0,
        None,
        None,
        None,
        ctypes.byref(store),
        ctypes.byref(message),
        None,
    ):
        return None
    try:
        size = wintypes.DWORD(0)
        if not _crypt32.CryptMsgGetParam(
            message, _CMSG_SIGNER_INFO_PARAM, 0, None, ctypes.byref(size)
        ):
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not _crypt32.CryptMsgGetParam(
            message, _CMSG_SIGNER_INFO_PARAM, 0, buffer, ctypes.byref(size)
        ):
            return None
        signer = _SignerInfoPrefix.from_buffer(buffer)
        wanted = _CertInfo(Issuer=signer.Issuer, SerialNumber=signer.SerialNumber)
        context = _crypt32.CertFindCertificateInStore(
            store, _ENCODING, 0, _CERT_FIND_SUBJECT_CERT, ctypes.byref(wanted), None
        )
        if not context:
            return None
        try:
            return _name(context)
        finally:
            _crypt32.CertFreeCertificateContext(context)
    finally:
        if message:
            _crypt32.CryptMsgClose(message)
        if store:
            _crypt32.CertCloseStore(store, 0)


# --- Almacenes de certificados -----------------------------------------------------------------


class StoreLocation:
    CURRENT_USER = "CurrentUser"
    LOCAL_MACHINE = "LocalMachine"


_LOCATIONS = {
    StoreLocation.CURRENT_USER: _CERT_SYSTEM_STORE_CURRENT_USER,
    StoreLocation.LOCAL_MACHINE: _CERT_SYSTEM_STORE_LOCAL_MACHINE,
}
STORE_NAMES = ("My", "Root", "CA", "TrustedPublisher", "TrustedPeople")


@dataclass(frozen=True)
class CertificateRecord:
    location: str
    store: str
    thumbprint: str
    subject: str | None
    issuer: str | None
    friendly_name: str | None
    serial_number: str
    not_before: datetime
    not_after: datetime
    has_private_key: bool
    key_provider: str | None
    der: bytes


def _filetime(value: wintypes.FILETIME) -> datetime:
    ticks = (value.dwHighDateTime << 32) | value.dwLowDateTime
    return _WINDOWS_EPOCH + timedelta(microseconds=ticks / 10)


def _property(context: Any, prop: int) -> bytes | None:
    size = wintypes.DWORD(0)
    if not _crypt32.CertGetCertificateContextProperty(context, prop, None, ctypes.byref(size)):
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if not _crypt32.CertGetCertificateContextProperty(context, prop, buffer, ctypes.byref(size)):
        return None
    return buffer.raw[: size.value]


def _key_provider(context: Any) -> str | None:
    size = wintypes.DWORD(0)
    if not _crypt32.CertGetCertificateContextProperty(
        context, _CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(size)
    ):
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if not _crypt32.CertGetCertificateContextProperty(
        context, _CERT_KEY_PROV_INFO_PROP_ID, buffer, ctypes.byref(size)
    ):
        return None
    info = _KeyProvInfo.from_buffer(buffer)
    return info.pwszProvName or ""


def _record(location: str, store: str, context: Any) -> CertificateRecord:
    cert = context.contents
    info = cert.pCertInfo.contents
    der = ctypes.string_at(cert.pbCertEncoded, cert.cbCertEncoded)
    serial = ctypes.string_at(info.SerialNumber.pbData, info.SerialNumber.cbData)
    friendly = _property(context, _CERT_FRIENDLY_NAME_PROP_ID)
    provider = _key_provider(context)
    return CertificateRecord(
        location=location,
        store=store,
        thumbprint=hashlib.sha1(der).hexdigest().upper(),  # noqa: S324 - huella estándar de Windows
        subject=_name(context),
        issuer=_name(context, issuer=True),
        friendly_name=friendly.decode("utf-16-le").rstrip("\x00") or None if friendly else None,
        # El número de serie se guarda en orden little-endian; Windows lo muestra al revés.
        serial_number=serial[::-1].hex().upper(),
        not_before=_filetime(info.NotBefore),
        not_after=_filetime(info.NotAfter),
        has_private_key=provider is not None,
        key_provider=provider or None,
        der=der,
    )


def _open(location: str, store: str, writable: bool) -> int:
    flags = _LOCATIONS[location] | _CERT_STORE_OPEN_EXISTING_FLAG
    flags |= _CERT_STORE_MAXIMUM_ALLOWED_FLAG if writable else _CERT_STORE_READONLY_FLAG
    handle = _crypt32.CertOpenStore(
        _CERT_STORE_PROV_SYSTEM_W, 0, None, flags, ctypes.c_wchar_p(store)
    )
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def list_certificates(location: str, store: str) -> Iterator[CertificateRecord]:
    handle = _open(location, store, writable=False)
    try:
        context = _crypt32.CertEnumCertificatesInStore(handle, None)
        while context:
            yield _record(location, store, context)
            context = _crypt32.CertEnumCertificatesInStore(handle, context)
    finally:
        _crypt32.CertCloseStore(handle, 0)


def delete_certificate(location: str, store: str, thumbprint: str) -> bool:
    """Elimina el certificado con esa huella. Devuelve False si no estaba."""
    handle = _open(location, store, writable=True)
    try:
        context = _crypt32.CertEnumCertificatesInStore(handle, None)
        while context:
            if _record(location, store, context).thumbprint == thumbprint.upper():
                duplicate = _crypt32.CertDuplicateCertificateContext(context)
                _crypt32.CertFreeCertificateContext(context)
                if not _crypt32.CertDeleteCertificateFromStore(duplicate):
                    raise ctypes.WinError(ctypes.get_last_error())
                return True
            context = _crypt32.CertEnumCertificatesInStore(handle, context)
        return False
    finally:
        _crypt32.CertCloseStore(handle, 0)
