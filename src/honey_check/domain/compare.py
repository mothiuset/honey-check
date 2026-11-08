"""Comparación de dos inventarios, fila por fila: lo que cambió y también lo que sigue igual.

Cada fila dice en qué estado quedó el dato (`same`, `changed`, `added`, `removed` o `unknown`) para
que la interfaz pueda mostrar solo las diferencias, solo lo igual o todo.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import Enum, StrEnum
from typing import Any

from .inventory import Inventory, MemoryModule, PhysicalDisk
from .observed import Model, Observed


class RowState(StrEnum):
    SAME = "same"
    CHANGED = "changed"
    ADDED = "added"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class ValueKind(StrEnum):
    TEXT = "text"
    BYTES = "bytes"
    BOOL = "bool"
    DATE = "date"


class ComparisonRow(Model):
    area: str
    field: str
    kind: ValueKind = ValueKind.TEXT
    before: str | None
    after: str | None
    state: RowState


class Comparison(Model):
    base_id: str
    target_id: str
    same_device: bool | None
    rows: list[ComparisonRow]
    software: list[ComparisonRow]
    not_comparable: list[str]

    @property
    def changes(self) -> list[ComparisonRow]:
        """Filas de equipo, hardware y sistema que no coinciden (sin dato en ambos no cuenta)."""
        return [row for row in self.rows if row.state not in (RowState.SAME, RowState.UNKNOWN)]


def _text(value: Any) -> str | None:
    if isinstance(value, Observed):
        value = value.value
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _same_device(base: Inventory, target: Inventory) -> bool | None:
    if base.device is None or target.device is None:
        return None
    for first, second in (
        (base.device.serial_number.value, target.device.serial_number.value),
        (base.device.system_uuid.value, target.device.system_uuid.value),
    ):
        if first and second:
            return first == second
    return None


def _module_key(module: MemoryModule) -> str:
    return (
        f"{_text(module.slot) or '?'}: {_text(module.capacity_bytes) or '?'} B "
        f"{_text(module.memory_type) or '?'} {_text(module.part_number) or '?'}"
    )


def _disk_key(disk: PhysicalDisk) -> str:
    return f"{_text(disk.model) or '?'} ({_text(disk.serial_number) or 'sin serial'})"


class _Rows:
    def __init__(self) -> None:
        self.items: list[ComparisonRow] = []
        self.not_comparable: list[str] = []

    def field(
        self, area: str, name: str, before: Any, after: Any, kind: ValueKind = ValueKind.TEXT
    ) -> None:
        first, second = _text(before), _text(after)
        if first is None and second is None:
            state = RowState.UNKNOWN
        elif first == second:
            state = RowState.SAME
        else:
            state = RowState.CHANGED
        self.items.append(
            ComparisonRow(area=area, field=name, kind=kind, before=first, after=second, state=state)
        )

    def elements(self, area: str, name: str, before: list[str], after: list[str]) -> None:
        """Piezas repetibles (módulos, discos, tarjetas): cada una sigue, aparece o se retira."""
        remaining = Counter(after)
        for item in sorted(before):
            if remaining[item]:
                remaining[item] -= 1
                state, second = RowState.SAME, item
            else:
                state, second = RowState.REMOVED, None
            self.items.append(
                ComparisonRow(area=area, field=name, before=item, after=second, state=state)
            )
        for item in sorted(remaining.elements()):
            self.items.append(
                ComparisonRow(area=area, field=name, before=None, after=item, state=RowState.ADDED)
            )


def _compare_device(base: Inventory, target: Inventory, out: _Rows) -> None:
    first, second = base.device, target.device
    if not (first and second):
        out.not_comparable.append("device")
        return
    for name in ("hostname", "manufacturer", "model", "serial_number", "device_type", "asset_tag"):
        out.field("device", name, getattr(first, name), getattr(second, name))
    out.field("device", "baseboard", first.baseboard.product, second.baseboard.product)
    out.field("device", "firmware_version", first.firmware.version, second.firmware.version)
    out.field("device", "firmware_mode", first.firmware.mode, second.firmware.mode)
    out.field("device", "domain", first.membership.name, second.membership.name)


def _compare_hardware(base: Inventory, target: Inventory, out: _Rows) -> None:
    first, second = base.hardware, target.hardware
    if first.processor and second.processor:
        out.elements(
            "processor",
            "processor",
            [_text(p.model) or "?" for p in first.processor.processors],
            [_text(p.model) or "?" for p in second.processor.processors],
        )
        out.field(
            "processor",
            "cores",
            first.processor.total_physical_cores,
            second.processor.total_physical_cores,
        )
        out.field(
            "processor",
            "logical_processors",
            first.processor.total_logical_processors,
            second.processor.total_logical_processors,
        )
    else:
        out.not_comparable.append("processor")

    if first.memory and second.memory:
        out.field(
            "memory",
            "installed_bytes",
            first.memory.installed_bytes,
            second.memory.installed_bytes,
            ValueKind.BYTES,
        )
        out.field("memory", "total_slots", first.memory.total_slots, second.memory.total_slots)
        out.elements(
            "memory",
            "module",
            [_module_key(m) for m in first.memory.modules],
            [_module_key(m) for m in second.memory.modules],
        )
    else:
        out.not_comparable.append("memory")

    if first.storage and second.storage:
        out.elements(
            "storage",
            "disk",
            [_disk_key(d) for d in first.storage.disks],
            [_disk_key(d) for d in second.storage.disks],
        )
    else:
        out.not_comparable.append("storage")

    if first.graphics and second.graphics:
        out.elements(
            "graphics",
            "adapter",
            [_text(a.name) or "?" for a in first.graphics.adapters],
            [_text(a.name) or "?" for a in second.graphics.adapters],
        )
    else:
        out.not_comparable.append("graphics")

    if first.tpm and second.tpm:
        out.field("tpm", "present", first.tpm.present, second.tpm.present, ValueKind.BOOL)
        out.field("tpm", "spec_version", first.tpm.spec_version, second.tpm.spec_version)
    else:
        out.not_comparable.append("tpm")


def _compare_system(base: Inventory, target: Inventory, out: _Rows) -> None:
    first, second = base.operating_system, target.operating_system
    if first and second:
        for name in ("name", "edition_id", "display_version", "full_build", "architecture"):
            out.field("operating_system", name, getattr(first, name), getattr(second, name))
        out.field(
            "operating_system",
            "installed_at",
            first.installed_at,
            second.installed_at,
            ValueKind.DATE,
        )
    else:
        out.not_comparable.append("operating_system")

    security, other = base.security, target.security
    if security and other:
        for name in ("secure_boot_enabled", "uac_enabled", "memory_integrity_running"):
            out.field(
                "security", name, getattr(security, name), getattr(other, name), ValueKind.BOOL
            )
        out.field(
            "security",
            "code_integrity_policy",
            security.code_integrity_policy,
            other.code_integrity_policy,
        )
        out.field(
            "security",
            "powershell_language_mode",
            security.powershell_language_mode,
            other.powershell_language_mode,
        )
    else:
        out.not_comparable.append("security")


def _compare_software(base: Inventory, target: Inventory, out: _Rows) -> list[ComparisonRow]:
    if not (base.software and target.software):
        out.not_comparable.append("software")
        return []
    before_items = {item.id: item for item in base.software.items}
    after_items = {item.id: item for item in target.software.items}
    rows: list[ComparisonRow] = []
    for key, item in after_items.items():
        previous = before_items.get(key)
        after = item.version.value
        if previous is None:
            state, before = RowState.ADDED, None
        else:
            before = previous.version.value
            state = RowState.SAME if before == after else RowState.CHANGED
        rows.append(
            ComparisonRow(area="software", field=item.name, before=before, after=after, state=state)
        )
    rows.extend(
        ComparisonRow(
            area="software",
            field=item.name,
            before=item.version.value,
            after=None,
            state=RowState.REMOVED,
        )
        for key, item in before_items.items()
        if key not in after_items
    )
    return sorted(rows, key=lambda row: row.field.lower())


def compare_inventories(
    base_id: str, base: Inventory, target_id: str, target: Inventory
) -> Comparison:
    out = _Rows()
    _compare_device(base, target, out)
    _compare_hardware(base, target, out)
    _compare_system(base, target, out)
    software = _compare_software(base, target, out)
    return Comparison(
        base_id=base_id,
        target_id=target_id,
        same_device=_same_device(base, target),
        rows=out.items,
        software=software,
        not_comparable=out.not_comparable,
    )
