"""Nombre de archivo del inventario, derivado de datos del equipo que no son de confianza."""

from __future__ import annotations

import re
from datetime import datetime

FILE_PREFIX = "honey-check_"
FILE_SUFFIX = ".json"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)$", re.IGNORECASE)
_ID = re.compile(r"^honey-check_[A-Za-z0-9._-]{1,120}$")


def safe_hostname(hostname: str | None) -> str:
    cleaned = _UNSAFE.sub("_", hostname or "").strip("._-")[:63]
    if not cleaned or _RESERVED.match(cleaned):
        return "equipo-sin-nombre"
    return cleaned


def inventory_stem(hostname: str | None, moment: datetime, sequence: int = 0) -> str:
    suffix = f"_{sequence:02d}" if sequence else ""
    return f"{FILE_PREFIX}{safe_hostname(hostname)}_{moment:%Y-%m-%d_%H%M%S}{suffix}"


def is_valid_inventory_id(value: str) -> bool:
    return bool(_ID.match(value)) and ".." not in value
