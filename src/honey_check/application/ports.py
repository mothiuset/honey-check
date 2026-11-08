"""Puertos que la aplicación necesita del sistema; los implementa la infraestructura."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from honey_check.domain.inventory import Inventory, PathState
from honey_check.domain.peripherals import DeviceNode


class CollectionCancelled(Exception):
    """La recopilación se canceló o superó su tiempo límite."""


class CancelToken:
    def __init__(self, parent: CancelToken | None = None) -> None:
        self._event = threading.Event()
        self._parent = parent

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or (self._parent is not None and self._parent.cancelled)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CollectionCancelled


# --- CIM/WMI ----------------------------------------------------------------------------------


class CimErrorKind(StrEnum):
    ACCESS_DENIED = "access_denied"
    NOT_AVAILABLE = "not_available"  # clase o espacio de nombres inexistente en este equipo
    TIMEOUT = "timeout"
    TRANSIENT = "transient"  # RPC, proveedor WMI ocupado: admite un reintento limitado
    FAILED = "failed"


@dataclass(frozen=True)
class CimError:
    kind: CimErrorKind
    message: str


@dataclass(frozen=True)
class CimQuery:
    """Consulta de lectura fija, definida en el código. La API HTTP no puede aportar ninguna."""

    namespace: str
    class_name: str
    properties: tuple[str, ...]
    where: str | None = None

    @property
    def source(self) -> str:
        return f"cim:{self.namespace}/{self.class_name}"


CimRow = Mapping[str, Any]


@dataclass(frozen=True)
class CimResult:
    rows: tuple[CimRow, ...] = ()
    error: CimError | None = None
    retries: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None


class CimPort(Protocol):
    def query(
        self, queries: Sequence[CimQuery], cancel: CancelToken, timeout_s: float
    ) -> list[CimResult]: ...


# --- Registro ---------------------------------------------------------------------------------


class RegistryHive(StrEnum):
    LOCAL_MACHINE = "HKLM"
    CURRENT_USER = "HKCU"


class RegistryView(StrEnum):
    DEFAULT = "default"
    BITS_64 = "64"
    BITS_32 = "32"


class RegistryKeyMissing(Exception):
    pass


class RegistryAccessDenied(Exception):
    pass


class RegistryPort(Protocol):
    """Solo lectura: el contrato no ofrece ninguna operación de escritura."""

    def subkeys(self, hive: RegistryHive, path: str, view: RegistryView) -> list[str]: ...

    def values(self, hive: RegistryHive, path: str, view: RegistryView) -> dict[str, Any]: ...

    def last_write(self, hive: RegistryHive, path: str, view: RegistryView) -> datetime | None: ...


# --- Archivos ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FileMetadata:
    file_version: str | None = None
    product_version: str | None = None
    product_name: str | None = None
    file_description: str | None = None
    company_name: str | None = None
    machine: str | None = None  # arquitectura leída de la cabecera PE


class FileInspector(Protocol):
    """Lectura acotada de archivos. No recorre discos completos ni toca rutas de red."""

    def path_state(self, path: str) -> PathState: ...

    def list_executables(self, directory: str, limit: int) -> list[str]: ...

    def metadata(self, path: str) -> FileMetadata: ...

    def read_text(self, path: str, max_bytes: int) -> str | None: ...


@dataclass(frozen=True)
class SignatureResult:
    status: str
    signer: str | None = None


class SignatureInspector(Protocol):
    def inspect(
        self, paths: Sequence[str], cancel: CancelToken, timeout_s: float
    ) -> dict[str, SignatureResult]: ...


class IconExtractor(Protocol):
    """Iconos de programas como PNG pequeños; None cuando no hay ninguno utilizable."""

    def executable_icon(self, path: str) -> bytes | None: ...

    def package_logo(self, install_location: str, logo: str) -> bytes | None: ...


# --- Consultas nativas sin WMI -----------------------------------------------------------------


@dataclass(frozen=True)
class TpmNativeInfo:
    present: bool
    spec_version: str | None


@dataclass(frozen=True)
class NativeDisplayMode:
    device: str
    is_primary: bool
    width: int
    height: int
    refresh_hz: int | None


class NativeSystemPort(Protocol):
    def computer_name(self) -> str | None: ...

    def firmware_mode(self) -> str | None: ...

    def native_architecture(self) -> str | None: ...

    def is_elevated(self) -> bool | None: ...

    def tpm_info(self) -> TpmNativeInfo | None: ...

    def display_modes(self) -> list[NativeDisplayMode]: ...


# --- Árbol de dispositivos ---------------------------------------------------------------------


class DeviceTreePort(Protocol):
    """Nodos de dispositivo de las clases pedidas, conectados o no (solo lectura)."""

    def nodes(self, classes: Iterable[str]) -> list[DeviceNode]: ...


# --- Paquetes AppX ----------------------------------------------------------------------------


class AppxQueryError(Exception):
    def __init__(self, kind: CimErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class AppxPort(Protocol):
    def packages(self, cancel: CancelToken, timeout_s: float) -> list[Mapping[str, Any]]: ...


class PowerShellInfoPort(Protocol):
    def language_mode(self, cancel: CancelToken, timeout_s: float) -> str | None: ...


# --- Persistencia de inventarios ----------------------------------------------------------------


# Carpeta de datos que Honey Check crea junto al ejecutable (o en la carpeta alternativa).
DATA_DIR_NAME = "HoneyCheck-datos"


class StoreWriteError(Exception):
    """El destino no permite escribir: el inventario sigue en memoria para otra alternativa."""


@dataclass(frozen=True)
class SavedInventory:
    inventory_id: str
    path: Path
    device_key: str
    sequence: int
    previous_inventory_id: str | None = None


@dataclass(frozen=True)
class InventorySummary:
    inventory_id: str
    path: Path
    size_bytes: int
    device_key: str
    sequence: int | None = None
    collected_at: str | None = None
    hostname: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    device_type: str | None = None
    os_name: str | None = None
    domain: str | None = None
    status: str | None = None
    schema_version: str | None = None
    app_version: str | None = None
    # Motivo por el que el archivo no puede leerse; el resto de campos queda vacío.
    invalid_reason: str | None = None


@dataclass(frozen=True)
class DeviceSummary:
    device_key: str
    hostname: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    device_type: str | None
    os_name: str | None
    domain: str | None
    last_status: str | None
    inventory_count: int
    unreadable_count: int
    last_inventory_id: str | None
    last_collected_at: str | None
    first_collected_at: str | None


@dataclass(frozen=True)
class ImportReport:
    imported: int
    skipped: list[str]


class InventoryStore(Protocol):
    @property
    def root(self) -> Path: ...

    def use_root(self, root: Path) -> None: ...

    def ensure_root(self) -> bool: ...

    def save(self, inventory: Inventory) -> SavedInventory: ...

    def inventories(self, device_key: str | None = None) -> list[InventorySummary]: ...

    def devices(self) -> list[DeviceSummary]: ...

    def load(self, inventory_id: str) -> Inventory: ...

    def path_of(self, inventory_id: str) -> Path: ...

    def import_legacy(self, directory: Path) -> ImportReport: ...

    def reference(self) -> str | None: ...

    def icon_path(self, inventory_id: str, icon_id: str) -> Path: ...

    def set_reference(self, inventory_id: str) -> None: ...

    def summary(self, inventory_id: str) -> InventorySummary: ...

    # Borrar mueve a la papelera de la carpeta de datos: nada se elimina del disco.
    def delete_inventory(self, inventory_id: str) -> Path: ...

    def delete_device(self, device_key: str) -> tuple[int, Path]: ...


# --- Recursos de un módulo ----------------------------------------------------------------------


@dataclass
class CollectorPorts:
    """Lo que un módulo puede usar: siempre lectura, nunca escritura en el equipo."""

    cim: CimPort
    registry: RegistryPort
    files: FileInspector
    signatures: SignatureInspector
    native: NativeSystemPort
    appx: AppxPort
    powershell: PowerShellInfoPort
    icons: IconExtractor | None = None
    devices: DeviceTreePort | None = None
    extras: dict[str, Any] = field(default_factory=dict)
