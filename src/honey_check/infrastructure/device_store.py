"""Inventarios organizados por equipo y versionados, en una carpeta propia junto al ejecutable.

```
HoneyCheck-datos/
  equipos/<deviceKey>/equipo.json              resumen derivado del equipo
  equipos/<deviceKey>/inventarios/v0001_<UTC>.json
  indice.json                                  caché reconstruible; nunca la fuente de verdad
  papelera/<UTC>_<azar>/equipos/<deviceKey>/…  lo borrado, con su ruta original para recuperarlo
```

Cada análisis es un archivo nuevo: nada se sobrescribe. La escritura es atómica (temporal,
`fsync` y renombrado sin reemplazo), también en FAT32/exFAT.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from honey_check.application.ports import (
    DeviceSummary,
    ImportReport,
    InventorySummary,
    SavedInventory,
    StoreWriteError,
)
from honey_check.domain.inventory import Inventory
from honey_check.domain.migrations import UnsupportedSchemaError, load_document

log = logging.getLogger(__name__)

_LEGACY_PATTERN = "honey-check_*.json"
_INDEX_NAME = "indice.json"
_REFERENCE_NAME = "referencia.json"
_TRASH_NAME = "papelera"
_INDEX_FORMAT = "honey-check.index"
_INDEX_VERSION = 2  # 2 añade tipo, sistema y dominio: los índices antiguos se reconstruyen
_MAX_INVENTORY_BYTES = 64 * 1024 * 1024
_MAX_SEQUENCE_ATTEMPTS = 100
_DEVICE_DIR = re.compile(r"^[a-z0-9-]{1,64}$")
_INVENTORY_FILE = re.compile(r"^v(\d{4,})_[0-9TZ]{16}\.json$")
_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_ICON_ID = re.compile(r"^[0-9a-f]{16}$")


class InventoryNotFound(Exception):
    pass


class InventoryUnreadable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_valid_inventory_id(value: str) -> bool:
    return bool(_ID.match(value))


def is_directory_writable(directory: Path) -> bool:
    """Se prueba creando un archivo real: las ACL no cuentan toda la historia en una USB."""
    probe = directory / f".honey-check-probe-{secrets.token_hex(4)}.tmp"
    try:
        with probe.open("xb") as handle:
            handle.write(b"ok")
        probe.unlink()
    except OSError:
        return False
    return True


def write_new_file(target: Path, payload: bytes) -> None:
    """Crea `target` de forma atómica. Lanza FileExistsError si ya existe: nunca lo reemplaza."""
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.rename(target)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _replace_file(target: Path, payload: bytes) -> None:
    """Para archivos derivados (índice y resumen de equipo), que sí pueden regenerarse."""
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _serialize(inventory: Inventory) -> bytes:
    return json.dumps(inventory.to_document(), ensure_ascii=False, indent=2).encode("utf-8")


def _read_inventory(path: Path) -> Inventory:
    try:
        if path.stat().st_size > _MAX_INVENTORY_BYTES:
            raise InventoryUnreadable("file_too_large")
        document = json.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError as error:
        raise InventoryNotFound(path.name) from error
    except OSError as error:
        raise InventoryUnreadable("file_not_accessible") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InventoryUnreadable("invalid_json") from error
    if not isinstance(document, dict):
        raise InventoryUnreadable("invalid_json")
    try:
        return load_document(document)
    except UnsupportedSchemaError as error:
        raise InventoryUnreadable(str(error)) from error
    except ValidationError as error:
        raise InventoryUnreadable("schema_validation_failed") from error


def _summary_of(inventory: Inventory, path: Path, size: int) -> InventorySummary:
    device = inventory.device
    collection = inventory.collection
    return InventorySummary(
        inventory_id=collection.inventory_id,
        path=path,
        size_bytes=size,
        device_key=collection.device_key,
        sequence=collection.sequence,
        collected_at=collection.started_at.astimezone(UTC).isoformat(),
        hostname=device.hostname.value if device else None,
        manufacturer=device.manufacturer.value if device else None,
        model=device.model.value if device else None,
        serial_number=device.serial_number.value if device else None,
        device_type=device.device_type.value.value if device and device.device_type.value else None,
        os_name=inventory.operating_system.name.value if inventory.operating_system else None,
        domain=device.membership.name.value if device else None,
        status=collection.status.value,
        schema_version=inventory.schema_info.version,
        app_version=collection.app_version,
    )


def _invalid_id(relative: str) -> str:
    return "archivo-" + hashlib.sha256(relative.encode()).hexdigest()[:20]


@dataclass
class _IndexEntry:
    relative: str
    size: int
    mtime_ns: int
    summary: dict[str, Any]


class DeviceInventoryStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.RLock()

    # --- Ubicación -------------------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    def use_root(self, root: Path) -> None:
        with self._lock:
            self._root = root

    def ensure_root(self) -> bool:
        try:
            (self._root / "equipos").mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return True

    def _devices_dir(self) -> Path:
        return self._root / "equipos"

    # --- Escritura -------------------------------------------------------------------------------

    def save(self, inventory: Inventory) -> SavedInventory:
        # Se comprueba que el documento cumple el contrato antes de tocar el disco.
        load_document(json.loads(_serialize(inventory)))
        key = inventory.collection.device_key
        if not _DEVICE_DIR.match(key):
            raise StoreWriteError("clave de equipo no válida")
        with self._lock:
            folder = self._devices_dir() / key / "inventarios"
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise StoreWriteError(f"carpeta no disponible ({type(error).__name__})") from error
            history = self.inventories(key)
            previous = history[0].inventory_id if history else None
            sequence = self._next_sequence(folder)
            moment = inventory.collection.started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            for _ in range(_MAX_SEQUENCE_ATTEMPTS):
                versioned = inventory.model_copy(
                    update={
                        "collection": inventory.collection.model_copy(
                            update={"sequence": sequence, "previous_inventory_id": previous}
                        )
                    }
                )
                target = folder / f"v{sequence:04d}_{moment}.json"
                try:
                    write_new_file(target, _serialize(versioned))
                except FileExistsError:
                    sequence += 1
                    continue
                except OSError as error:
                    raise StoreWriteError(
                        f"no se pudo escribir ({type(error).__name__})"
                    ) from error
                self._write_icons(key, inventory.attachments)
                self._write_device_summary(key)
                return SavedInventory(
                    versioned.collection.inventory_id, target, key, sequence, previous
                )
        raise StoreWriteError("demasiadas versiones simultáneas del mismo equipo")

    def _write_icons(self, key: str, attachments: dict[str, bytes]) -> None:
        """Los iconos se comparten entre versiones del mismo equipo: solo se escriben los nuevos."""
        if not attachments:
            return
        folder = self._devices_dir() / key / "iconos"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.info("No se pudo crear la carpeta de iconos")
            return
        for identifier, data in attachments.items():
            target = folder / f"{identifier}.png"
            if not _ICON_ID.match(identifier) or target.exists():
                continue
            try:
                write_new_file(target, data)
            except FileExistsError:
                continue
            except OSError:
                log.info("No se pudo guardar un icono")
                return

    def icon_path(self, inventory_id: str, icon_id: str) -> Path:
        if not _ICON_ID.match(icon_id):
            raise InventoryNotFound(icon_id)
        summary = next((s for s in self._summaries() if s.inventory_id == inventory_id), None)
        if summary is None:
            raise InventoryNotFound(inventory_id)
        path = self._devices_dir() / summary.device_key / "iconos" / f"{icon_id}.png"
        if not path.is_file():
            raise InventoryNotFound(icon_id)
        return path

    @staticmethod
    def _next_sequence(folder: Path) -> int:
        highest = 0
        try:
            names = [entry.name for entry in os.scandir(folder)]
        except OSError:
            names = []
        for name in names:
            match = _INVENTORY_FILE.match(name)
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1

    def _write_device_summary(self, key: str) -> None:
        devices = [d for d in self.devices() if d.device_key == key]
        if not devices:
            return
        path = self._devices_dir() / key / "equipo.json"
        payload = json.dumps(asdict(devices[0]), ensure_ascii=False, indent=2).encode("utf-8")
        try:
            _replace_file(path, payload)
        except OSError:
            log.info("No se pudo actualizar el resumen del equipo")

    # --- Lectura e índice ------------------------------------------------------------------------

    def _inventory_files(self) -> Iterable[tuple[str, Path, os.stat_result]]:
        base = self._devices_dir()
        try:
            devices = [e for e in os.scandir(base) if e.is_dir() and _DEVICE_DIR.match(e.name)]
        except OSError:
            return
        for device in devices:
            folder = Path(device.path) / "inventarios"
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                if entry.is_file() and _INVENTORY_FILE.match(entry.name):
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    yield f"{device.name}/inventarios/{entry.name}", Path(entry.path), stat

    def _load_index(self) -> dict[str, _IndexEntry]:
        try:
            raw = json.loads((self._root / _INDEX_NAME).read_text(encoding="utf-8"))
            if raw.get("format") != _INDEX_FORMAT or raw.get("version") != _INDEX_VERSION:
                return {}
            return {
                item["relative"]: _IndexEntry(
                    item["relative"], item["size"], item["mtimeNs"], item["summary"]
                )
                for item in raw["entries"]
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {}

    def _save_index(self, entries: dict[str, _IndexEntry]) -> None:
        payload = {
            "format": _INDEX_FORMAT,
            "version": _INDEX_VERSION,
            "entries": [
                {
                    "relative": e.relative,
                    "size": e.size,
                    "mtimeNs": e.mtime_ns,
                    "summary": e.summary,
                }
                for e in entries.values()
            ],
        }
        try:
            _replace_file(
                self._root / _INDEX_NAME, json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
        except OSError:
            log.info("No se pudo guardar el índice; se reconstruirá en la próxima lectura")

    def _summaries(self) -> list[InventorySummary]:
        with self._lock:
            cached = self._load_index()
            current: dict[str, _IndexEntry] = {}
            changed = False
            for relative, path, stat in self._inventory_files():
                entry = cached.get(relative)
                if entry and entry.size == stat.st_size and entry.mtime_ns == stat.st_mtime_ns:
                    current[relative] = entry
                    continue
                changed = True
                current[relative] = _IndexEntry(
                    relative, stat.st_size, stat.st_mtime_ns, self._summarize(relative, path, stat)
                )
            if changed or set(cached) != set(current):
                self._save_index(current)
            return [self._from_index(e) for e in current.values()]

    def _summarize(self, relative: str, path: Path, stat: os.stat_result) -> dict[str, Any]:
        try:
            summary = _summary_of(_read_inventory(path), path, stat.st_size)
        except InventoryUnreadable as error:
            summary = InventorySummary(
                _invalid_id(relative),
                path,
                stat.st_size,
                device_key=relative.split("/")[0],
                invalid_reason=error.reason,
            )
        except InventoryNotFound:
            summary = InventorySummary(
                _invalid_id(relative),
                path,
                0,
                device_key=relative.split("/")[0],
                invalid_reason="file_not_accessible",
            )
        data = asdict(summary)
        data["path"] = relative
        return data

    def _from_index(self, entry: _IndexEntry) -> InventorySummary:
        data = dict(entry.summary)
        data["path"] = self._devices_dir() / entry.relative
        return InventorySummary(**data)

    def inventories(self, device_key: str | None = None) -> list[InventorySummary]:
        summaries = self._summaries()
        if device_key is not None:
            summaries = [s for s in summaries if s.device_key == device_key]
        return sorted(
            summaries, key=lambda s: (s.collected_at or "", s.sequence or 0), reverse=True
        )

    def devices(self) -> list[DeviceSummary]:
        grouped: dict[str, list[InventorySummary]] = {}
        for summary in self._summaries():
            grouped.setdefault(summary.device_key, []).append(summary)
        devices: list[DeviceSummary] = []
        for key, items in grouped.items():
            valid = sorted(
                (s for s in items if not s.invalid_reason),
                key=lambda s: s.collected_at or "",
                reverse=True,
            )
            latest = valid[0] if valid else None
            devices.append(
                DeviceSummary(
                    device_key=key,
                    hostname=latest.hostname if latest else None,
                    manufacturer=latest.manufacturer if latest else None,
                    model=latest.model if latest else None,
                    serial_number=latest.serial_number if latest else None,
                    device_type=latest.device_type if latest else None,
                    os_name=latest.os_name if latest else None,
                    domain=latest.domain if latest else None,
                    last_status=latest.status if latest else None,
                    inventory_count=len(valid),
                    unreadable_count=len(items) - len(valid),
                    last_inventory_id=latest.inventory_id if latest else None,
                    last_collected_at=latest.collected_at if latest else None,
                    first_collected_at=valid[-1].collected_at if valid else None,
                )
            )
        return sorted(devices, key=lambda d: d.last_collected_at or "", reverse=True)

    def path_of(self, inventory_id: str) -> Path:
        if not is_valid_inventory_id(inventory_id):
            raise InventoryNotFound(inventory_id)
        for summary in self._summaries():
            if summary.inventory_id == inventory_id:
                return summary.path
        raise InventoryNotFound(inventory_id)

    def summary(self, inventory_id: str) -> InventorySummary:
        if is_valid_inventory_id(inventory_id):
            for summary in self._summaries():
                if summary.inventory_id == inventory_id:
                    return summary
        raise InventoryNotFound(inventory_id)

    def load(self, inventory_id: str) -> Inventory:
        return _read_inventory(self.path_of(inventory_id))

    # --- Papelera --------------------------------------------------------------------------------

    def _to_trash(self, source: Path) -> Path:
        """Mueve `source` a la papelera conservando su ruta bajo `equipos` para poder devolverlo."""
        relative = source.relative_to(self._devices_dir())
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self._root / _TRASH_NAME / f"{stamp}_{secrets.token_hex(3)}" / "equipos" / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        except OSError as error:
            raise StoreWriteError(
                f"no se pudo mover a la papelera ({type(error).__name__})"
            ) from error
        return target

    def _forget_reference(self, inventory_ids: set[str]) -> None:
        if self.reference() in inventory_ids:
            with contextlib.suppress(OSError):
                (self._root / _REFERENCE_NAME).unlink()

    def delete_inventory(self, inventory_id: str) -> Path:
        with self._lock:
            summary = self.summary(inventory_id)
            target = self._to_trash(summary.path)
            self._forget_reference({inventory_id})
            if self.inventories(summary.device_key):
                self._write_device_summary(summary.device_key)
            else:
                with contextlib.suppress(OSError):
                    (self._devices_dir() / summary.device_key / "equipo.json").unlink()
            log.info("Versión %s del equipo movida a la papelera", summary.sequence)
            return target

    def delete_device(self, device_key: str) -> tuple[int, Path]:
        """Mueve la carpeta entera del equipo (versiones, iconos y resumen) a la papelera."""
        folder = self._devices_dir() / device_key
        if not _DEVICE_DIR.match(device_key) or not folder.is_dir():
            raise InventoryNotFound(device_key)
        with self._lock:
            ids = {s.inventory_id for s in self.inventories(device_key)}
            target = self._to_trash(folder)
            self._forget_reference(ids)
            log.info("Equipo con %d versiones movido a la papelera", len(ids))
            return len(ids), target

    # --- Referencia para comparar -------------------------------------------------------------

    def reference(self) -> str | None:
        """Inventario de un equipo que funcionaba bien, con el que comparar a los demás."""
        try:
            data = json.loads((self._root / _REFERENCE_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = data.get("inventoryId") if isinstance(data, dict) else None
        return value if isinstance(value, str) and is_valid_inventory_id(value) else None

    def set_reference(self, inventory_id: str) -> None:
        self.path_of(inventory_id)  # Solo inventarios que existen.
        payload = json.dumps({"inventoryId": inventory_id}).encode("utf-8")
        try:
            _replace_file(self._root / _REFERENCE_NAME, payload)
        except OSError as error:
            raise StoreWriteError(f"no se pudo guardar ({type(error).__name__})") from error

    # --- Inventarios sueltos de la versión anterior ----------------------------------------------

    def import_legacy(self, directory: Path) -> ImportReport:
        """Mueve los `honey-check_*.json` sueltos a su equipo. Solo borra el original verificado."""
        imported = 0
        skipped: list[str] = []
        try:
            files = sorted(directory.glob(_LEGACY_PATTERN))
        except OSError:
            return ImportReport(0, [])
        known = {s.inventory_id for s in self._summaries()}
        for path in files:
            try:
                inventory = _read_inventory(path)
            except (InventoryUnreadable, InventoryNotFound) as error:
                skipped.append(f"{path.name}: {getattr(error, 'reason', 'no accesible')}")
                continue
            if inventory.collection.inventory_id not in known:
                try:
                    saved = self.save(inventory)
                    _read_inventory(saved.path)
                except (StoreWriteError, InventoryUnreadable, InventoryNotFound, OSError):
                    skipped.append(f"{path.name}: no se pudo guardar en la carpeta de datos")
                    continue
                known.add(inventory.collection.inventory_id)
            try:
                path.unlink()
            except OSError:
                skipped.append(f"{path.name}: guardado, pero el original no se pudo retirar")
                continue
            imported += 1
        if imported:
            log.info("Se movieron %d inventarios sueltos a la carpeta de datos", imported)
        return ImportReport(imported, skipped)
