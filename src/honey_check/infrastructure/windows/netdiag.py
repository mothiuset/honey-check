"""Diagnóstico de red y dominio con APIs nativas (sin depender del idioma de las herramientas)."""

from __future__ import annotations

import ctypes
import socket
import struct
from ctypes import wintypes
from dataclasses import dataclass

_iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
_netapi32 = ctypes.WinDLL("netapi32", use_last_error=True)
_dnsapi = ctypes.WinDLL("dnsapi", use_last_error=True)


# --- Ping (ICMP) ----------------------------------------------------------------------------------


class _IpOptions(ctypes.Structure):
    _fields_ = (
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    )


class _EchoReply(ctypes.Structure):
    _fields_ = (
        ("Address", ctypes.c_ulong),
        ("Status", ctypes.c_ulong),
        ("RoundTripTime", ctypes.c_ulong),
        ("DataSize", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort),
        ("Data", ctypes.c_void_p),
        ("Options", _IpOptions),
    )


_iphlpapi.IcmpCreateFile.restype = wintypes.HANDLE
_iphlpapi.IcmpCloseHandle.argtypes = (wintypes.HANDLE,)
_iphlpapi.IcmpSendEcho.argtypes = (
    wintypes.HANDLE,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_ushort,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
)
_iphlpapi.IcmpSendEcho.restype = ctypes.c_ulong


@dataclass(frozen=True)
class PingResult:
    host: str
    address: str | None
    sent: int
    received: int
    min_ms: int | None
    avg_ms: int | None
    max_ms: int | None
    error: str | None = None


def resolve_ipv4(host: str) -> str | None:
    try:
        return str(socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0])
    except (OSError, IndexError):
        return None


def ping(host: str, count: int = 4, timeout_ms: int = 1500) -> PingResult:
    address = resolve_ipv4(host)
    if address is None:
        return PingResult(host, None, 0, 0, None, None, None, "no se pudo resolver el nombre")
    handle = _iphlpapi.IcmpCreateFile()
    if not handle or handle == wintypes.HANDLE(-1).value:
        return PingResult(host, address, 0, 0, None, None, None, "ICMP no disponible")
    payload = b"honey-check-ping"
    reply_size = ctypes.sizeof(_EchoReply) + len(payload) + 8
    buffer = ctypes.create_string_buffer(reply_size)
    target = struct.unpack("<L", socket.inet_aton(address))[0]
    times: list[int] = []
    try:
        for _ in range(count):
            got = _iphlpapi.IcmpSendEcho(
                handle, target, payload, len(payload), None, buffer, reply_size, timeout_ms
            )
            if got:
                reply = _EchoReply.from_buffer(buffer)
                if reply.Status == 0:
                    times.append(int(reply.RoundTripTime))
    finally:
        _iphlpapi.IcmpCloseHandle(handle)
    if not times:
        return PingResult(host, address, count, 0, None, None, None)
    return PingResult(
        host, address, count, len(times), min(times), sum(times) // len(times), max(times)
    )


def tcp_port_open(host: str, port: int, timeout_s: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


# --- Controlador de dominio -----------------------------------------------------------------------


class _Guid(ctypes.Structure):
    _fields_ = (
        ("a", ctypes.c_ulong),
        ("b", ctypes.c_ushort),
        ("c", ctypes.c_ushort),
        ("d", ctypes.c_ubyte * 8),
    )


class _DcInfo(ctypes.Structure):
    _fields_ = (
        ("DomainControllerName", wintypes.LPWSTR),
        ("DomainControllerAddress", wintypes.LPWSTR),
        ("DomainControllerAddressType", ctypes.c_ulong),
        ("DomainGuid", _Guid),
        ("DomainName", wintypes.LPWSTR),
        ("DnsForestName", wintypes.LPWSTR),
        ("Flags", ctypes.c_ulong),
        ("DcSiteName", wintypes.LPWSTR),
        ("ClientSiteName", wintypes.LPWSTR),
    )


_netapi32.DsGetDcNameW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.POINTER(_DcInfo)),
)
_netapi32.DsGetDcNameW.restype = ctypes.c_ulong
_netapi32.NetApiBufferFree.argtypes = (ctypes.c_void_p,)
_netapi32.NetRemoteTOD.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p))
_netapi32.NetRemoteTOD.restype = ctypes.c_ulong

_DS_FORCE_REDISCOVERY = 0x1
_DS_RETURN_DNS_NAME = 0x40000000
_DS_IP_REQUIRED = 0x200


@dataclass(frozen=True)
class DomainController:
    name: str
    address: str | None
    domain: str | None
    forest: str | None
    site: str | None
    client_site: str | None


def find_domain_controller(
    domain: str | None, *, rediscover: bool = False
) -> tuple[DomainController | None, int]:
    """Controlador de dominio y código de error de Windows (0 si lo encontró)."""
    pointer = ctypes.POINTER(_DcInfo)()
    flags = _DS_RETURN_DNS_NAME | _DS_IP_REQUIRED | (_DS_FORCE_REDISCOVERY if rediscover else 0)
    code = _netapi32.DsGetDcNameW(None, domain, None, None, flags, ctypes.byref(pointer))
    if code != 0:
        return None, int(code)
    try:
        info = pointer.contents
        return (
            DomainController(
                name=(info.DomainControllerName or "").lstrip("\\"),
                address=(info.DomainControllerAddress or "").lstrip("\\") or None,
                domain=info.DomainName,
                forest=info.DnsForestName,
                site=info.DcSiteName,
                client_site=info.ClientSiteName,
            ),
            0,
        )
    finally:
        _netapi32.NetApiBufferFree(pointer)


def remote_time_offset(server: str) -> float | None:
    """Segundos de diferencia entre la hora del servidor y la de este equipo (positivo: el
    servidor va adelante).
    """
    import time

    buffer = ctypes.c_void_p()
    if _netapi32.NetRemoteTOD(f"\\\\{server}", ctypes.byref(buffer)) != 0 or not buffer:
        return None
    try:
        elapsed = ctypes.c_ulong.from_address(
            buffer.value or 0
        ).value  # tod_elapsedt: segundos desde 1970 UTC
        return float(elapsed) - time.time()
    finally:
        _netapi32.NetApiBufferFree(buffer)


# --- DNS ------------------------------------------------------------------------------------------

_dnsapi.DnsFlushResolverCache.restype = wintypes.BOOL


def flush_dns_cache() -> bool:
    return bool(_dnsapi.DnsFlushResolverCache())
