"""Búsqueda, filtros, orden y paginación de equipos: pensado para miles de equipos en la USB."""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .ports import DeviceSummary

MAX_PAGE_SIZE = 200


class DeviceSort(StrEnum):
    LAST_ANALYSIS = "last"
    NAME = "name"
    MANUFACTURER = "manufacturer"
    MODEL = "model"
    VERSIONS = "versions"
    OPERATING_SYSTEM = "os"


@dataclass(frozen=True)
class DeviceQuery:
    text: str = ""
    manufacturer: str | None = None
    device_type: str | None = None
    os_name: str | None = None
    status: str | None = None
    sort: DeviceSort = DeviceSort.LAST_ANALYSIS
    descending: bool = True
    page: int = 1
    size: int = 25


@dataclass(frozen=True)
class DevicePage:
    items: list[DeviceSummary]
    total: int
    page: int
    size: int
    # Valores disponibles para cada filtro, con cuántos equipos tienen cada uno.
    facets: dict[str, list[tuple[str, int]]] = field(default_factory=dict)

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.size))


def _fold(text: str | None) -> str:
    """Sin mayúsculas ni tildes: «lenovo» encuentra «LENOVO» y «portatil» encuentra «portátil»."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).casefold()


def _haystack(device: DeviceSummary) -> str:
    fields = (
        device.hostname,
        device.manufacturer,
        device.model,
        device.serial_number,
        device.os_name,
        device.domain,
        device.device_key,
    )
    return " ".join(_fold(value) for value in fields if value)


_SORT_KEYS: dict[DeviceSort, Callable[[DeviceSummary], Any]] = {
    DeviceSort.LAST_ANALYSIS: lambda d: d.last_collected_at or "",
    DeviceSort.NAME: lambda d: _fold(d.hostname),
    DeviceSort.MANUFACTURER: lambda d: (_fold(d.manufacturer), _fold(d.model)),
    DeviceSort.MODEL: lambda d: _fold(d.model),
    DeviceSort.VERSIONS: lambda d: d.inventory_count,
    DeviceSort.OPERATING_SYSTEM: lambda d: _fold(d.os_name),
}


def _facet(
    devices: Sequence[DeviceSummary], pick: Callable[[DeviceSummary], str | None]
) -> list[tuple[str, int]]:
    counts = Counter(value for value in (pick(d) for d in devices) if value)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def query_devices(devices: Sequence[DeviceSummary], query: DeviceQuery) -> DevicePage:
    words = [w for w in _fold(query.text).split() if w]
    matches = [
        d
        for d in devices
        if all(word in _haystack(d) for word in words)
        and (query.manufacturer is None or d.manufacturer == query.manufacturer)
        and (query.device_type is None or d.device_type == query.device_type)
        and (query.os_name is None or d.os_name == query.os_name)
        and (query.status is None or d.last_status == query.status)
    ]
    matches.sort(key=_SORT_KEYS[query.sort], reverse=query.descending)
    size = max(1, min(query.size, MAX_PAGE_SIZE))
    pages = max(1, -(-len(matches) // size))
    page = max(1, min(query.page, pages))
    start = (page - 1) * size
    # Las facetas se calculan sobre el texto buscado, no sobre los demás filtros: así se ve qué
    # se puede elegir sin quedar atrapado en una combinación vacía.
    by_text = [d for d in devices if all(word in _haystack(d) for word in words)]
    return DevicePage(
        items=matches[start : start + size],
        total=len(matches),
        page=page,
        size=size,
        facets={
            "manufacturer": _facet(by_text, lambda d: d.manufacturer),
            "deviceType": _facet(by_text, lambda d: d.device_type),
            "os": _facet(by_text, lambda d: d.os_name),
            "status": _facet(by_text, lambda d: d.last_status),
        },
    )
