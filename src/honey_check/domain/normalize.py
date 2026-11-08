"""Normalización de valores crudos de SMBIOS/WMI sin inventar datos."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .observed import Observed, Reason

# Valores de relleno que los fabricantes dejan en SMBIOS, frecuentes en equipos ensamblados.
_PLACEHOLDERS = frozenset(
    {
        "to be filled by o.e.m.",
        "to be filled by oem",
        "default string",
        "default",
        "system serial number",
        "system manufacturer",
        "system product name",
        "system version",
        "system sku",
        "base board serial number",
        "base board product name",
        "base board manufacturer",
        "chassis serial number",
        "chassis manufacturer",
        "asset-1234567890",
        "not applicable",
        "not specified",
        "not available",
        "not present",
        "no asset tag",
        "no asset information",
        "none",
        "null",
        "n/a",
        "na",
        "unknown",
        "undefined",
        "invalid",
        "oem",
        "o.e.m.",
        "empty",
        "serial",
        "0123456789",
        "123456789",
        "1234567890",
        "manufacturer00",
        "partnum0",
        "serial0",
    }
)
_REPEATED_FILLER = re.compile(r"^(0+|f+|x+|\*+|-+|\.+|1+)$", re.IGNORECASE)
_NULL_UUIDS = {"00000000-0000-0000-0000-000000000000", "ffffffff-ffff-ffff-ffff-ffffffffffff"}


def is_placeholder(text: str) -> bool:
    lowered = text.strip().lower()
    return (
        lowered in _PLACEHOLDERS or lowered in _NULL_UUIDS or bool(_REPEATED_FILLER.match(lowered))
    )


def clean_text(raw: Any) -> str | None:
    """Texto recortado y sin caracteres de control; None si no contiene nada."""
    if raw is None:
        return None
    text = "".join(ch for ch in str(raw) if ch.isprintable()).strip()
    return text or None


def observed_text(raw: Any, source: str) -> Observed[str]:
    text = clean_text(raw)
    if text is None:
        return Observed[str].unknown(Reason.NOT_REPORTED, source)
    if is_placeholder(text):
        return Observed[str].unknown(Reason.PLACEHOLDER, source, raw=text)
    return Observed[str].reported(text, source)


def observed_positive_int(raw: Any, source: str) -> Observed[int]:
    """Muchos proveedores usan 0 como «sin dato»: no se presenta como una medida real."""
    if raw is None or isinstance(raw, bool):
        return Observed[int].unknown(Reason.NOT_REPORTED, source)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return Observed[int].unknown(Reason.INVALID_VALUE, source, raw=str(raw)[:64])
    if value <= 0:
        return Observed[int].unknown(Reason.NOT_REPORTED, source)
    return Observed[int].reported(value, source)


def observed_bool(raw: Any, source: str) -> Observed[bool]:
    if isinstance(raw, bool):
        return Observed[bool].reported(raw, source)
    return Observed[bool].unknown(Reason.NOT_REPORTED, source)


def parse_iso_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def observed_datetime(raw: Any, source: str) -> Observed[datetime]:
    moment = parse_iso_datetime(raw)
    if moment is not None:
        return Observed[datetime].reported(moment, source)
    if raw in (None, ""):
        return Observed[datetime].unknown(Reason.NOT_REPORTED, source)
    return Observed[datetime].unknown(Reason.INVALID_VALUE, source, raw=str(raw)[:64])


def parse_yyyymmdd(raw: Any) -> str | None:
    """Fecha de instalación del Registro (AAAAMMDD) a ISO 8601; None si no es una fecha real."""
    text = clean_text(raw)
    if text is None or not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return None
