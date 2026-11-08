"""Casos de uso que consume la presentación: analizar, guardar, consultar y comparar."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from honey_check.domain.compare import Comparison, compare_inventories
from honey_check.domain.inventory import Inventory

from .device_query import DevicePage, DeviceQuery, query_devices
from .ports import (
    DATA_DIR_NAME,
    DeviceSummary,
    InventoryStore,
    InventorySummary,
    SavedInventory,
    StoreWriteError,
)
from .scan import ScanCoordinator, ScanProgress

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkspaceStatus:
    directory: Path
    available: bool
    writable: bool


@dataclass(frozen=True)
class CurrentDevice:
    """El equipo donde se ejecuta Honey Check, para no confundirlo con los de la USB."""

    device_key: str
    identity_basis: str
    hostname: str | None


@dataclass(frozen=True)
class ExportFailure:
    """Último análisis que no pudo guardarse. Sigue en memoria hasta guardarlo o descartarlo."""

    reason: str
    inventory_id: str


class AlternateDirectoryRejected(Exception):
    pass


class NoPendingInventory(Exception):
    pass


class FolderOutsideData(Exception):
    """Solo se abren carpetas de la carpeta de datos: la petición no elige rutas arbitrarias."""


class InventoryService:
    def __init__(
        self,
        store: InventoryStore,
        coordinator_factory: Callable[[Callable[[Inventory], None]], ScanCoordinator],
        check_writable: Callable[[Path], bool],
        on_saved: Callable[[SavedInventory], None] | None = None,
        on_export_failed: Callable[[str], None] | None = None,
        *,
        is_network_path: Callable[[str], bool],
    ) -> None:
        self._store = store
        self._check_writable = check_writable
        self._is_network_path = is_network_path
        self._on_saved = on_saved
        self._on_export_failed = on_export_failed
        self._lock = threading.Lock()
        self._pending: Inventory | None = None
        self._failure: ExportFailure | None = None
        self._last_saved: SavedInventory | None = None
        self._current: CurrentDevice | None = None
        self.scans = coordinator_factory(self._finished)

    # --- Equipo actual ---------------------------------------------------------------------------

    @property
    def current_device(self) -> CurrentDevice | None:
        with self._lock:
            return self._current

    def set_current_device(self, device: CurrentDevice) -> None:
        with self._lock:
            self._current = device

    # --- Análisis --------------------------------------------------------------------------------

    def start_scan(self) -> str:
        return self.scans.start()

    def cancel_scan(self) -> bool:
        return self.scans.cancel()

    def progress(self) -> ScanProgress:
        return self.scans.snapshot()

    def _finished(self, inventory: Inventory) -> None:
        # Un análisis completo identifica al equipo mejor que la sonda inicial.
        self.set_current_device(
            CurrentDevice(
                inventory.collection.device_key,
                inventory.collection.identity_basis,
                inventory.device.hostname.value if inventory.device else None,
            )
        )
        try:
            saved = self._store.save(inventory)
        except StoreWriteError as error:
            log.warning("No se pudo guardar el inventario: %s", error)
            with self._lock:
                self._pending = inventory
                self._failure = ExportFailure(str(error), inventory.collection.inventory_id)
            if self._on_export_failed:
                self._on_export_failed(str(error))
            return
        self._remember(saved)

    def _remember(self, saved: SavedInventory) -> None:
        with self._lock:
            self._pending = None
            self._failure = None
            self._last_saved = saved
        log.info("Inventario guardado: versión %d del equipo", saved.sequence)
        if self._on_saved:
            self._on_saved(saved)

    # --- Exportación alternativa -----------------------------------------------------------------

    @property
    def export_failure(self) -> ExportFailure | None:
        with self._lock:
            return self._failure

    @property
    def last_saved(self) -> SavedInventory | None:
        with self._lock:
            return self._last_saved

    def pending_inventory(self) -> Inventory:
        with self._lock:
            if self._pending is None:
                raise NoPendingInventory
            return self._pending

    def export_pending_to(self, raw_directory: str) -> SavedInventory:
        """Guarda el análisis pendiente bajo la carpeta que el técnico eligió de forma explícita.

        La petición solo aporta una carpeta local existente; dentro se crea la misma estructura de
        datos. Las rutas de red se rechazan para no bloquear ni sacar datos del equipo.
        """
        directory = validate_alternate_directory(raw_directory, self._is_network_path)
        if not self._check_writable(directory):
            raise AlternateDirectoryRejected("not_writable")
        inventory = self.pending_inventory()
        previous_root = self._store.root
        self._store.use_root(directory / DATA_DIR_NAME)
        try:
            saved = self._store.save(inventory)
        except StoreWriteError:
            self._store.use_root(previous_root)
            raise
        self._remember(saved)
        return saved

    def discard_pending(self) -> None:
        with self._lock:
            self._pending = None
            self._failure = None

    # --- Consulta --------------------------------------------------------------------------------

    def workspace(self) -> WorkspaceStatus:
        root = self._store.root
        available = _is_directory(root.parent) and self._store.ensure_root()
        return WorkspaceStatus(
            directory=root,
            available=available,
            writable=available and self._check_writable(root),
        )

    def history(self, device_key: str | None = None) -> list[InventorySummary]:
        return self._store.inventories(device_key)

    def devices(self) -> list[DeviceSummary]:
        return self._store.devices()

    def search_devices(self, query: DeviceQuery) -> DevicePage:
        return query_devices(self._store.devices(), query)

    def load(self, inventory_id: str) -> Inventory:
        return self._store.load(inventory_id)

    def summary(self, inventory_id: str) -> InventorySummary:
        return self._store.summary(inventory_id)

    def folder_in_data(self, raw: str | None) -> Path:
        """La carpeta de datos o una carpeta existente dentro de ella (completa o relativa)."""
        root = self._store.root
        if not raw:
            return root
        try:
            candidate = (root / raw).resolve(strict=True)
            inside = candidate.is_dir() and candidate.is_relative_to(root.resolve(strict=True))
        except (OSError, ValueError, RuntimeError):
            inside = False
        if not inside:
            raise FolderOutsideData(raw)
        return candidate

    # --- Borrado (a la papelera) ---------------------------------------------------------------

    def delete_inventory(self, inventory_id: str) -> Path:
        return self._store.delete_inventory(inventory_id)

    def delete_device(self, device_key: str) -> tuple[int, Path]:
        return self._store.delete_device(device_key)

    def file_of(self, inventory_id: str) -> Path:
        return self._store.path_of(inventory_id)

    def reference(self) -> str | None:
        return self._store.reference()

    def icon_of(self, inventory_id: str, icon_id: str) -> Path:
        return self._store.icon_path(inventory_id, icon_id)

    def set_reference(self, inventory_id: str) -> None:
        self._store.set_reference(inventory_id)

    def compare(self, base_id: str, target_id: str) -> Comparison:
        return compare_inventories(
            base_id, self._store.load(base_id), target_id, self._store.load(target_id)
        )

    def shutdown(self) -> None:
        self.scans.shutdown()


def _is_directory(directory: Path) -> bool:
    try:
        return directory.is_dir()
    except OSError:
        return False


def validate_alternate_directory(raw: str, is_network_path: Callable[[str], bool]) -> Path:
    text = raw.strip().strip('"')
    if not text or len(text) > 1024 or "\x00" in text:
        raise AlternateDirectoryRejected("invalid_path")
    if text.startswith(("\\\\", "//")):
        raise AlternateDirectoryRejected("network_path_not_allowed")
    path = Path(text)
    if not path.is_absolute():
        raise AlternateDirectoryRejected("path_must_be_absolute")
    if ".." in path.parts:
        raise AlternateDirectoryRejected("invalid_path")
    # Consult the platform policy before any directory lookup or writable probe.
    # A drive-letter path can target SMB without using UNC syntax.
    if is_network_path(str(path)):
        raise AlternateDirectoryRejected("network_path_not_allowed")
    if not _is_directory(path):
        raise AlternateDirectoryRejected("directory_not_found")
    return path
