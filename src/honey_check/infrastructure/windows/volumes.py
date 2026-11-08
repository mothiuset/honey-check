"""Discos físicos con sus particiones y volúmenes, en vivo (una USB recién conectada aparece).

Las clases MSFT_* del espacio de almacenamiento se leen sin administrador en menos de un segundo.
Partición y volumen se unen por el GUID de la partición (GPT) o, si no hay, por la letra.
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass, field

from honey_check.application.ports import CancelToken, CimQuery
from honey_check.infrastructure.windows.wmi import WmiCim

_NS = "root/Microsoft/Windows/Storage"
_BUS = {
    1: "SCSI",
    3: "ATA",
    6: "Fibre Channel",
    7: "USB",
    8: "RAID",
    10: "SAS",
    11: "SATA",
    12: "SD",
    13: "MMC",
    14: "Virtual",
    15: "Disco virtual (VHD)",
    17: "NVMe",
}
_MEDIA = {3: "HDD", 4: "SSD", 5: "SCM"}
_HEALTH = {0: "Saludable", 1: "Con advertencias", 2: "Con fallas"}
# Particiones GPT que Windows reserva: se muestran, pero no se analizan.
_RESERVED_GPT = {
    "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}": "Partición de arranque EFI",
    "{e3c9e316-0b5c-4db8-817d-f92df00215ae}": "Reservada de Microsoft",
    "{de94bba4-06d1-4d40-a16a-bfd50179d6ac}": "Recuperación de Windows",
}


@dataclass
class Partition:
    number: int
    size: int
    letter: str | None
    label: str | None = None
    file_system: str | None = None
    free: int | None = None
    reserved: str | None = None  # por qué no se analiza

    @property
    def root(self) -> str | None:
        return f"{self.letter}:\\" if self.letter else None

    @property
    def title(self) -> str:
        if self.letter:
            return f"{self.letter}: {self.label}" if self.label else f"{self.letter}:"
        return self.reserved or self.label or f"Partición {self.number}"


@dataclass
class Disk:
    number: int
    name: str
    size: int
    bus: str | None
    media: str | None
    health: str | None
    is_system: bool
    partitions: list[Partition] = field(default_factory=list)

    @property
    def title(self) -> str:
        kind = " ".join(part for part in (self.bus, self.media) if part)
        return f"Disco {self.number}: {self.name}" + (f" ({kind})" if kind else "")


def _rows(cim: WmiCim, cls: str, props: tuple[str, ...]) -> list[dict[str, object]]:
    result = cim.query([CimQuery(_NS, cls, props)], CancelToken(), 15.0)[0]
    if result.error:
        raise OSError(result.error.message)
    return [dict(row) for row in result.rows]


def _letter(value: object) -> str | None:
    if isinstance(value, int) and value:
        return chr(value)
    if isinstance(value, str) and value.strip("\x00 "):
        return value.strip("\x00 ")[0]
    return None


def _int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def list_disks() -> list[Disk]:
    cim = WmiCim()
    disks = _rows(
        cim, "MSFT_Disk", ("Number", "FriendlyName", "Size", "BusType", "HealthStatus", "IsSystem")
    )
    physical = {
        str(row.get("DeviceId")): row
        for row in _rows(cim, "MSFT_PhysicalDisk", ("DeviceId", "MediaType"))
    }
    partitions = _rows(
        cim,
        "MSFT_Partition",
        ("DiskNumber", "PartitionNumber", "DriveLetter", "Size", "GptType", "IsBoot", "Guid"),
    )
    volumes = _rows(
        cim,
        "MSFT_Volume",
        ("DriveLetter", "FileSystemLabel", "FileSystem", "SizeRemaining", "Path"),
    )
    by_guid = {
        str(v.get("Path") or "").lower().removeprefix("\\\\?\\volume").strip("\\"): v
        for v in volumes
    }
    by_letter = {_letter(v.get("DriveLetter")): v for v in volumes if _letter(v.get("DriveLetter"))}

    result = []
    for row in sorted(disks, key=lambda r: _int(r.get("Number"))):
        number = _int(row.get("Number"))
        media = physical.get(str(number), {}).get("MediaType")
        disk = Disk(
            number=number,
            name=str(row.get("FriendlyName") or "Disco sin nombre").strip(),
            size=_int(row.get("Size")),
            bus=_BUS.get(_int(row.get("BusType"))),
            media=_MEDIA.get(_int(media)),
            health=_HEALTH.get(_int(row.get("HealthStatus"))),
            is_system=bool(row.get("IsSystem")),
        )
        for part in sorted(
            (p for p in partitions if _int(p.get("DiskNumber")) == number),
            key=lambda p: _int(p.get("PartitionNumber")),
        ):
            letter = _letter(part.get("DriveLetter"))
            guid = str(part.get("Guid") or "").lower()
            volume = by_guid.get(guid) or (by_letter.get(letter) if letter else None) or {}
            reserved = _RESERVED_GPT.get(str(part.get("GptType") or "").lower())
            if reserved is None and not letter:
                reserved = "Sin letra: Windows no la muestra"
            entry = Partition(
                number=_int(part.get("PartitionNumber")),
                size=_int(part.get("Size")),
                letter=letter,
                # La partición con Windows se nombra así si no tiene etiqueta propia.
                label=str(volume.get("FileSystemLabel") or "")
                or ("Windows" if part.get("IsBoot") else None),
                file_system=str(volume.get("FileSystem") or "") or None,
                free=_int(volume.get("SizeRemaining")) if volume else None,
                reserved=reserved if not letter else None,
            )
            if entry.letter and entry.free is None:
                with contextlib.suppress(OSError):
                    entry.free = shutil.disk_usage(entry.root or "").free
            disk.partitions.append(entry)
        result.append(disk)
    return result
