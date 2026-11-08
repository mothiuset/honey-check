"""Identidad estable de un equipo entre análisis, aunque cambie de nombre o de dominio."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from .inventory import DeviceIdentity
from .normalize import is_placeholder

# UUID que algunos firmwares repiten en miles de placas: no identifican a un equipo.
_SHARED_UUIDS = frozenset(
    {
        "03000200-0400-0500-0006-000700080009",
        "00020003-0004-0005-0006-000700080009",
        "12345678-1234-5678-90ab-cddeefaabbcc",
    }
)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class IdentityBasis(StrEnum):
    """De qué dato sale la clave, de más a menos fiable."""

    SMBIOS_UUID = "smbios_uuid"
    SERIAL = "manufacturer_serial"
    BASEBOARD_SERIAL = "baseboard_serial"
    HOSTNAME = "hostname"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeviceKey:
    value: str
    basis: IdentityBasis


UNKNOWN_DEVICE = DeviceKey("sin-identificar", IdentityBasis.UNKNOWN)


def _digest(basis: IdentityBasis, material: str) -> DeviceKey:
    raw = f"{basis.value}:{material}".encode()
    return DeviceKey(hashlib.sha256(raw).hexdigest()[:24], basis)


def _usable(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    return None if not text or is_placeholder(text) else text


def device_key(identity: DeviceIdentity | None) -> DeviceKey:
    """La clave no contiene el serial en claro: el nombre de la carpeta no revela datos."""
    if identity is None:
        return UNKNOWN_DEVICE
    uuid = _usable(identity.system_uuid.value)
    if uuid:
        normalized = uuid.lower()
        if _UUID.match(normalized) and normalized not in _SHARED_UUIDS:
            return _digest(IdentityBasis.SMBIOS_UUID, normalized)
    serial = _usable(identity.serial_number.value)
    if serial:
        maker = (_usable(identity.manufacturer.value) or "").lower()
        return _digest(IdentityBasis.SERIAL, f"{maker}|{serial.upper()}")
    board = _usable(identity.baseboard.serial_number.value)
    if board:
        maker = (_usable(identity.baseboard.manufacturer.value) or "").lower()
        return _digest(IdentityBasis.BASEBOARD_SERIAL, f"{maker}|{board.upper()}")
    hostname = _usable(identity.hostname.value)
    if hostname:
        return _digest(IdentityBasis.HOSTNAME, hostname.upper())
    return UNKNOWN_DEVICE
