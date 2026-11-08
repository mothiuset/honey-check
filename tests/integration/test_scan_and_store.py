"""Análisis completo con puertos simulados (mocks) y archivos reales en una carpeta temporal."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from fakes import FakeCim, make_ports
from fixtures.vendors import ACER, HP
from honey_check.application.ports import (
    CancelToken,
    CimError,
    CimErrorKind,
    CimResult,
    StoreWriteError,
)
from honey_check.application.scan import ScanAlreadyRunning, ScanCoordinator, ScanState
from honey_check.application.service import (
    AlternateDirectoryRejected,
    InventoryService,
    NoPendingInventory,
    validate_alternate_directory,
)
from honey_check.composition import default_collectors
from honey_check.domain.inventory import (
    SCHEMA_VERSION,
    CollectionStatus,
    Inventory,
    ModuleStatus,
)
from honey_check.domain.migrations import load_document
from honey_check.infrastructure import device_store
from honey_check.infrastructure.device_store import (
    DeviceInventoryStore,
    InventoryNotFound,
    InventoryUnreadable,
    is_directory_writable,
)


class FakeCollector:
    def __init__(
        self,
        name: str,
        behaviour: Callable[[Any], BaseModel] | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.name = name
        self.timeout_s = timeout_s
        self._behaviour = behaviour

    def collect(self, ctx: Any) -> BaseModel:
        assert self._behaviour is not None
        return self._behaviour(ctx)


def run_scan(collectors: list[Any], ports: Any = None) -> Inventory:
    received: list[Inventory] = []
    coordinator = ScanCoordinator(collectors, ports or make_ports(), "0.0.0", None, received.append)
    coordinator.start()
    assert coordinator.wait(30)
    assert received, coordinator.snapshot().detail
    return received[0]


def full_ports() -> Any:
    return make_ports(cim=FakeCim(HP))


@pytest.fixture
def inventory() -> Inventory:
    return run_scan(default_collectors(), full_ports())


class TestModuleIsolation:
    def test_complete_scan(self, inventory: Inventory) -> None:
        assert inventory.device is not None
        assert inventory.device.manufacturer.value == "HP"
        assert inventory.hardware.memory is not None
        assert inventory.hardware.memory.module_count == 2
        assert {m.name for m in inventory.modules} == {c.name for c in default_collectors()}
        assert inventory.schema_info.version == SCHEMA_VERSION

    def test_software_failure_does_not_stop_hardware(self) -> None:
        def explode(ctx: Any) -> BaseModel:
            raise RuntimeError("C:\\Users\\persona-ficticia\\datos-sensibles")

        collectors = [
            c if c.name != "software" else FakeCollector("software", explode)
            for c in default_collectors()
        ]
        result = run_scan(collectors, full_ports())
        assert result.software is None
        assert result.hardware.memory is not None
        assert result.collection.status is CollectionStatus.PARTIAL
        report = next(m for m in result.modules if m.name == "software")
        assert report.status is ModuleStatus.FAILED
        error = next(e for e in result.errors if e.module == "software")
        assert error.code == "unexpected_error"
        # El mensaje de una excepción puede arrastrar rutas: no llega al JSON.
        assert "persona-ficticia" not in error.message

    def test_security_failure_does_not_stop_inventory(self) -> None:
        def explode(ctx: Any) -> BaseModel:
            raise OSError("fallo simulado")

        collectors = [
            c if c.name != "security" else FakeCollector("security", explode)
            for c in default_collectors()
        ]
        result = run_scan(collectors, full_ports())
        assert result.security is None
        assert result.software is not None
        assert result.device is not None

    def test_all_wmi_failing_still_produces_an_honest_document(self) -> None:
        class BrokenCim:
            def query(self, queries: Any, cancel: Any, timeout_s: float) -> list[CimResult]:
                error = CimError(CimErrorKind.FAILED, "WMI simulado roto")
                return [CimResult(error=error) for _ in queries]

        result = run_scan(default_collectors(), make_ports(cim=BrokenCim()))
        assert result.collection.status is CollectionStatus.PARTIAL
        assert result.device is None
        assert result.hardware.processor is None
        # El software no depende de WMI.
        assert result.software is not None
        assert result.errors

    def test_module_with_invalid_data_is_rejected_alone(self) -> None:
        def invalid(ctx: Any) -> BaseModel:
            from honey_check.domain.observed import Observed

            return Observed[str](value="x", confidence="reported")  # sin origen: viola el contrato

        collectors = [
            c if c.name != "tpm" else FakeCollector("tpm", invalid) for c in default_collectors()
        ]
        result = run_scan(collectors, full_ports())
        assert result.hardware.tpm is None
        assert next(e for e in result.errors if e.module == "tpm").code == "invalid_data"


class TestTimeoutsAndCancellation:
    def test_hung_module_times_out_without_blocking_others(self) -> None:
        release = threading.Event()

        def hang(ctx: Any) -> BaseModel:
            release.wait(20)
            raise AssertionError("no debía llegar")

        collectors = [
            FakeCollector("tpm", hang, timeout_s=0.2),
            *[c for c in default_collectors() if c.name != "tpm"],
        ]
        started = time.monotonic()
        result = run_scan(collectors, full_ports())
        release.set()
        assert time.monotonic() - started < 15
        report = next(m for m in result.modules if m.name == "tpm")
        assert report.status is ModuleStatus.TIMEOUT
        assert next(e for e in result.errors if e.module == "tpm").code == "module_timeout"
        assert result.hardware.tpm is None
        assert result.device is not None

    def test_module_honouring_cancel_token_stops_fast(self) -> None:
        def cooperative(ctx: Any) -> BaseModel:
            while True:
                ctx.cancel.raise_if_cancelled()
                time.sleep(0.01)

        collectors = [FakeCollector("tpm", cooperative, timeout_s=0.1)]
        started = time.monotonic()
        result = run_scan(collectors)
        assert time.monotonic() - started < 3
        assert result.modules[0].status is ModuleStatus.TIMEOUT
        assert any(e.code == "module_timeout" for e in result.errors)

    def test_cancel_stops_scan_and_exports_nothing(self) -> None:
        def slow(ctx: Any) -> BaseModel:
            while True:
                ctx.cancel.raise_if_cancelled()
                time.sleep(0.01)

        received: list[Inventory] = []
        coordinator = ScanCoordinator(
            [FakeCollector(f"m{i}", slow, timeout_s=60) for i in range(6)],
            make_ports(),
            "0",
            None,
            received.append,
        )
        coordinator.start()
        time.sleep(0.1)
        assert coordinator.cancel()
        assert coordinator.wait(10)
        snapshot = coordinator.snapshot()
        assert snapshot.state is ScanState.CANCELLED
        assert received == []
        assert {m.status for m in snapshot.modules} == {"cancelled"}

    def test_only_one_scan_at_a_time(self) -> None:
        release = threading.Event()

        def wait(ctx: Any) -> BaseModel:
            while not release.is_set():
                ctx.cancel.raise_if_cancelled()
                time.sleep(0.01)
            raise ValueError("fin")

        coordinator = ScanCoordinator(
            [FakeCollector("m", wait)], make_ports(), "0", None, lambda _: None
        )
        coordinator.start()
        with pytest.raises(ScanAlreadyRunning):
            coordinator.start()
        release.set()
        assert coordinator.wait(10)
        coordinator.start()
        assert coordinator.wait(10)

    def test_progress_is_visible_during_scan(self) -> None:
        release = threading.Event()
        seen: dict[str, Any] = {}

        def wait(ctx: Any) -> BaseModel:
            release.wait(10)
            raise ValueError("fin")

        coordinator = ScanCoordinator(
            [FakeCollector("a", wait), FakeCollector("b", wait)],
            make_ports(),
            "0",
            None,
            lambda _: None,
            max_parallel=1,
        )
        coordinator.start()
        time.sleep(0.2)
        snapshot = coordinator.snapshot()
        seen["statuses"] = [m.status for m in snapshot.modules]
        assert snapshot.total == 2
        assert snapshot.completed == 0
        release.set()
        assert coordinator.wait(10)
        assert seen["statuses"] == ["running", "pending"]
        assert coordinator.snapshot().completed == 2

    def test_cancelled_token_stops_new_cim_queries(self) -> None:
        token = CancelToken()
        child = CancelToken(parent=token)
        token.cancel()
        assert child.cancelled


class TestDeviceStore:
    def test_saves_under_its_device_folder_with_version(
        self, inventory: Inventory, tmp_path: Path
    ) -> None:
        saved = DeviceInventoryStore(tmp_path).save(inventory)
        key = inventory.collection.device_key
        assert saved.path.parent == tmp_path / "equipos" / key / "inventarios"
        assert saved.path.name.startswith("v0001_")
        assert saved.sequence == 1
        assert saved.previous_inventory_id is None
        document = json.loads(saved.path.read_text(encoding="utf-8"))
        assert document["schema"] == {"name": "honey-check.inventory", "version": SCHEMA_VERSION}
        assert document["collection"]["sequence"] == 1
        assert document["collection"]["deviceKey"] == key
        assert load_document(document).collection.inventory_id == saved.inventory_id
        summary = json.loads((tmp_path / "equipos" / key / "equipo.json").read_text("utf-8"))
        assert summary["inventory_count"] == 1

    def test_folder_names_do_not_reveal_personal_data(
        self, inventory: Inventory, tmp_path: Path
    ) -> None:
        saved = DeviceInventoryStore(tmp_path).save(inventory)
        relative = str(saved.path.relative_to(tmp_path))
        assert "PC-FICTICIO-01" not in relative
        assert "HP-SERIE-0002" not in relative

    def test_new_scans_are_new_versions_never_overwrites(
        self, inventory: Inventory, tmp_path: Path
    ) -> None:
        store = DeviceInventoryStore(tmp_path)
        first = store.save(inventory)
        before = first.path.read_bytes()
        second = store.save(
            inventory.model_copy(
                update={
                    "collection": inventory.collection.model_copy(
                        update={"inventory_id": "11111111-aaaa-4bbb-8ccc-000000000002"}
                    )
                }
            )
        )
        assert second.sequence == 2
        assert second.previous_inventory_id == first.inventory_id
        assert first.path.read_bytes() == before
        history = store.inventories(inventory.collection.device_key)
        assert [h.sequence for h in history] == [2, 1]

    def test_devices_are_separated(self, tmp_path: Path) -> None:
        store = DeviceInventoryStore(tmp_path)
        store.save(run_scan(default_collectors(), make_ports(cim=FakeCim(HP))))
        store.save(run_scan(default_collectors(), make_ports(cim=FakeCim(ACER))))
        devices = store.devices()
        assert {d.manufacturer for d in devices} == {"HP", "Acer"}
        assert all(d.inventory_count == 1 for d in devices)

    def test_unknown_device_is_kept_apart(self, tmp_path: Path) -> None:
        def fail(ctx: Any) -> BaseModel:
            raise OSError("sin identidad")

        result = run_scan([FakeCollector("identity", fail)])
        assert result.collection.device_key == "sin-identificar"
        saved = DeviceInventoryStore(tmp_path).save(result)
        assert "sin-identificar" in saved.path.parts

    def test_interrupted_write_leaves_no_partial_file(
        self, inventory: Inventory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def crash(fd: int) -> None:
            raise OSError("disco retirado")

        monkeypatch.setattr(device_store.os, "fsync", crash)
        with pytest.raises(StoreWriteError):
            DeviceInventoryStore(tmp_path).save(inventory)
        assert list(tmp_path.rglob("*.json")) == []
        assert list(tmp_path.rglob("*.tmp")) == []

    def test_interrupted_rename_leaves_no_partial_file(
        self, inventory: Inventory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def crash(self: Path, target: Path) -> None:
            raise OSError("disco retirado")

        monkeypatch.setattr(Path, "rename", crash)
        with pytest.raises(StoreWriteError):
            DeviceInventoryStore(tmp_path).save(inventory)
        assert list(tmp_path.rglob("v*.json")) == []

    def test_directory_writable_probe(self, tmp_path: Path) -> None:
        assert is_directory_writable(tmp_path)
        assert not is_directory_writable(tmp_path / "no-existe")
        assert list(tmp_path.iterdir()) == []


class TestIndexAndHistory:
    def test_index_is_written_and_reused(self, inventory: Inventory, tmp_path: Path) -> None:
        store = DeviceInventoryStore(tmp_path)
        saved = store.save(inventory)
        assert store.inventories()[0].inventory_id == saved.inventory_id
        index = json.loads((tmp_path / "indice.json").read_text(encoding="utf-8"))
        assert index["format"] == "honey-check.index"
        assert len(index["entries"]) == 1

    def test_index_does_not_reparse_unchanged_files(
        self, inventory: Inventory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = DeviceInventoryStore(tmp_path)
        store.save(inventory)
        store.inventories()

        def forbidden(path: Path) -> Inventory:
            raise AssertionError("no debía releer un archivo sin cambios")

        monkeypatch.setattr(device_store, "_read_inventory", forbidden)
        assert len(store.inventories()) == 1

    def test_corrupt_or_missing_index_is_rebuilt(
        self, inventory: Inventory, tmp_path: Path
    ) -> None:
        store = DeviceInventoryStore(tmp_path)
        store.save(inventory)
        (tmp_path / "indice.json").write_text("{roto", encoding="utf-8")
        assert len(store.inventories()) == 1
        (tmp_path / "indice.json").unlink()
        assert len(store.inventories()) == 1

    def test_deleted_file_disappears_from_index(self, inventory: Inventory, tmp_path: Path) -> None:
        store = DeviceInventoryStore(tmp_path)
        saved = store.save(inventory)
        saved.path.unlink()
        assert store.inventories() == []

    @pytest.mark.parametrize(
        ("content", "reason"),
        [
            (b"{", "invalid_json"),
            (b"[1,2]", "invalid_json"),
            (b'{"hello":"world"}', "el archivo no es un inventario de Honey Check"),
            (
                b'{"schema":{"name":"honey-check.inventory","version":"2.0.0"}}',
                "schema_validation_failed",
            ),
        ],
    )
    def test_corrupt_files_are_reported_not_fatal(
        self, tmp_path: Path, content: bytes, reason: str
    ) -> None:
        folder = tmp_path / "equipos" / "abc123" / "inventarios"
        folder.mkdir(parents=True)
        (folder / "v0001_20261105T100000Z.json").write_bytes(content)
        store = DeviceInventoryStore(tmp_path)
        summary = store.inventories()[0]
        assert summary.invalid_reason == reason
        with pytest.raises(InventoryUnreadable):
            store.load(summary.inventory_id)
        assert store.devices()[0].unreadable_count == 1

    def test_lookup_rejects_unknown_and_malformed_ids(self, tmp_path: Path) -> None:
        store = DeviceInventoryStore(tmp_path)
        for bad in ("..\\..\\secreto", "x", "00000000-0000-4000-8000-000000000000"):
            with pytest.raises(InventoryNotFound):
                store.load(bad)

    def test_foreign_folders_and_files_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "equipos" / "NO VALIDO").mkdir(parents=True)
        (tmp_path / "equipos" / "abc" / "inventarios").mkdir(parents=True)
        (tmp_path / "equipos" / "abc" / "inventarios" / "otro.json").write_text("{}", "utf-8")
        assert DeviceInventoryStore(tmp_path).inventories() == []


class TestLegacyImport:
    def legacy_file(self, folder: Path, inventory: Inventory, name: str) -> Path:
        document = inventory.to_document()
        document["schema"]["version"] = "1.0.0"
        collection = document["collection"]
        for field in ("deviceKey", "identityBasis", "sequence", "previousInventoryId"):
            collection.pop(field)
        path = folder / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_loose_inventories_are_moved_into_their_device(
        self, inventory: Inventory, tmp_path: Path
    ) -> None:
        usb = tmp_path / "usb"
        usb.mkdir()
        legacy = self.legacy_file(
            usb, inventory, "honey-check_PC-FICTICIO-01_2026-11-04_103000.json"
        )
        store = DeviceInventoryStore(usb / "HoneyCheck-datos")
        report = store.import_legacy(usb)
        assert report.imported == 1
        assert report.skipped == []
        assert not legacy.exists()
        moved = store.inventories()
        assert len(moved) == 1
        assert moved[0].device_key == inventory.collection.device_key
        assert moved[0].schema_version == SCHEMA_VERSION

    def test_import_is_idempotent(self, inventory: Inventory, tmp_path: Path) -> None:
        store = DeviceInventoryStore(tmp_path / "datos")
        self.legacy_file(tmp_path, inventory, "honey-check_a.json")
        store.import_legacy(tmp_path)
        self.legacy_file(tmp_path, inventory, "honey-check_a.json")
        report = store.import_legacy(tmp_path)
        assert report.imported == 1
        assert len(store.inventories()) == 1

    def test_unreadable_loose_file_is_left_untouched(self, tmp_path: Path) -> None:
        broken = tmp_path / "honey-check_roto.json"
        broken.write_text("{", encoding="utf-8")
        report = DeviceInventoryStore(tmp_path / "datos").import_legacy(tmp_path)
        assert report.imported == 0
        assert broken.exists()
        assert "honey-check_roto.json" in report.skipped[0]

    def test_original_is_kept_if_saving_fails(
        self, inventory: Inventory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy = self.legacy_file(tmp_path, inventory, "honey-check_b.json")
        store = DeviceInventoryStore(tmp_path / "datos")

        def fail(item: Inventory) -> Any:
            raise StoreWriteError("sin espacio")

        monkeypatch.setattr(store, "save", fail)
        report = store.import_legacy(tmp_path)
        assert report.imported == 0
        assert legacy.exists()


def make_service(directory: Path, ports: Any = None, **kwargs: Any) -> InventoryService:
    return InventoryService(
        DeviceInventoryStore(directory / "HoneyCheck-datos"),
        lambda on_finished: ScanCoordinator(
            default_collectors(), ports or full_ports(), "0.2.0", "abc", on_finished
        ),
        is_directory_writable,
        is_network_path=lambda _: False,
        **kwargs,
    )


class TestService:
    def test_scan_saves_into_data_folder_next_to_executable(self, tmp_path: Path) -> None:
        saved: list[Any] = []
        service = make_service(tmp_path, on_saved=saved.append)
        service.start_scan()
        assert service.scans.wait(30)
        assert tmp_path / "HoneyCheck-datos" in saved[0].path.parents
        assert not list(tmp_path.glob("*.json"))
        assert service.last_saved == saved[0]
        assert service.export_failure is None
        assert len(service.history()) == 1

    def test_scan_identifies_current_device(self, tmp_path: Path) -> None:
        service = make_service(tmp_path)
        service.start_scan()
        assert service.scans.wait(30)
        current = service.current_device
        assert current is not None
        assert current.hostname == "PC-FICTICIO-01"
        assert current.device_key == service.history()[0].device_key

    def test_history_filters_by_device(self, tmp_path: Path) -> None:
        service = make_service(tmp_path)
        service.start_scan()
        assert service.scans.wait(30)
        key = service.history()[0].device_key
        assert len(service.history(key)) == 1
        assert service.history("otro-equipo") == []

    def test_usb_removed_before_export_keeps_inventory_and_offers_alternative(
        self, tmp_path: Path
    ) -> None:
        usb = tmp_path / "usb"
        usb.mkdir()
        other = tmp_path / "otra-carpeta"
        other.mkdir()
        failures: list[str] = []
        service = make_service(usb, on_export_failed=failures.append)
        assert service.workspace().writable

        # Una carpeta que desaparece se simula borrándola y dejando un archivo en su lugar.
        shutil.rmtree(usb)
        usb.write_text("ya no es una carpeta", encoding="utf-8")

        status = service.workspace()
        assert status.available is False
        assert status.writable is False

        service.start_scan()
        assert service.scans.wait(30)
        assert failures
        assert service.export_failure is not None
        assert service.pending_inventory().device is not None

        saved = service.export_pending_to(str(other))
        assert other / "HoneyCheck-datos" in saved.path.parents
        assert service.export_failure is None
        with pytest.raises(NoPendingInventory):
            service.pending_inventory()
        assert service.workspace().directory == other / "HoneyCheck-datos"

    def test_alternate_folder_must_be_writable(self, tmp_path: Path) -> None:
        service = InventoryService(
            DeviceInventoryStore(tmp_path),
            lambda on_finished: ScanCoordinator(
                default_collectors(), full_ports(), "0", None, on_finished
            ),
            lambda directory: False,
            is_network_path=lambda _: False,
        )
        with pytest.raises(AlternateDirectoryRejected, match="not_writable"):
            service.export_pending_to(str(tmp_path))

    def test_export_without_pending(self, tmp_path: Path) -> None:
        with pytest.raises(NoPendingInventory):
            make_service(tmp_path).export_pending_to(str(tmp_path))

    @pytest.mark.parametrize(
        ("raw", "reason"),
        [
            ("", "invalid_path"),
            ("\\\\servidor-ficticio\\compartido", "network_path_not_allowed"),
            ("//servidor-ficticio/compartido", "network_path_not_allowed"),
            ("carpeta\\relativa", "path_must_be_absolute"),
            ("C:\\a\\..\\b", "invalid_path"),
            ("C:\\no-existe-honey-check", "directory_not_found"),
            ("a\x00b", "invalid_path"),
            ("x" * 2000, "invalid_path"),
        ],
    )
    def test_alternate_directory_validation(self, raw: str, reason: str) -> None:
        with pytest.raises(AlternateDirectoryRejected, match=reason):
            validate_alternate_directory(raw, lambda _: False)

    def test_compare_two_versions_of_the_same_device(self, tmp_path: Path) -> None:
        first = run_scan(default_collectors(), full_ports())
        rows = {
            **HP,
            "Win32_PhysicalMemory": [HP["Win32_PhysicalMemory"][0]],
            "Win32_ComputerSystem": [{**HP["Win32_ComputerSystem"][0], "Model": "Otro Modelo"}],
        }
        second = run_scan(default_collectors(), make_ports(cim=FakeCim(rows)))
        store = DeviceInventoryStore(tmp_path / "HoneyCheck-datos")
        a = store.save(first)
        b = store.save(second)
        assert b.sequence == 2
        comparison = make_service(tmp_path).compare(a.inventory_id, b.inventory_id)
        assert comparison.same_device is True
        fields = {(c.area, c.field) for c in comparison.changes}
        assert ("device", "model") in fields
        assert ("memory", "module") in fields
        assert ("memory", "installed_bytes") in fields


class TestSchemaContract:
    def test_published_schema_is_in_sync(self) -> None:
        """El contrato publicado no puede divergir de los modelos."""
        from honey_check.domain.inventory import SCHEMA_VERSION

        schema_path = (
            Path(__file__).parents[2] / "schema" / f"inventory-{SCHEMA_VERSION}.schema.json"
        )
        published = json.loads(schema_path.read_text(encoding="utf-8"))
        assert published == Inventory.model_json_schema(by_alias=True)


class TestIcons:
    PNG = b"\x89PNG\r\n\x1a\n" + b"icono-ficticio"

    def scanned_with_icon(self) -> Inventory:
        from honey_check.application.collection import CollectionContext

        class WithIcon:
            name = "identity"
            timeout_s = 5.0

            def collect(self, ctx: CollectionContext) -> BaseModel:
                ctx.attach(TestIcons.PNG)
                return default_collectors()[1].collect(ctx)

        return run_scan([WithIcon()], full_ports())

    def test_attachments_travel_with_the_inventory_and_are_saved_once(self, tmp_path: Path) -> None:
        inventory = self.scanned_with_icon()
        assert len(inventory.attachments) == 1
        assert "attachments" not in json.dumps(inventory.to_document())
        store = DeviceInventoryStore(tmp_path)
        first = store.save(inventory)
        second = store.save(
            inventory.model_copy(
                update={
                    "collection": inventory.collection.model_copy(
                        update={"inventory_id": "22222222-aaaa-4bbb-8ccc-000000000003"}
                    )
                }
            ).with_attachments(inventory.attachments)
        )
        icon_id = next(iter(inventory.attachments))
        icons = list((tmp_path / "equipos" / first.device_key / "iconos").iterdir())
        assert [p.name for p in icons] == [f"{icon_id}.png"]
        assert store.icon_path(second.inventory_id, icon_id).read_bytes() == self.PNG

    @pytest.mark.parametrize("bad", ["..-x", "ZZZZZZZZZZZZZZZZ", "abc"])
    def test_icon_lookup_validates_identifier(self, tmp_path: Path, bad: str) -> None:
        store = DeviceInventoryStore(tmp_path)
        saved = store.save(self.scanned_with_icon())
        with pytest.raises(InventoryNotFound):
            store.icon_path(saved.inventory_id, bad)

    def test_failed_module_attachments_are_discarded(self) -> None:
        def explode(ctx: Any) -> BaseModel:
            ctx.attach(b"\x89PNGdescartado")
            raise OSError("fallo simulado")

        assert run_scan([FakeCollector("identity", explode)]).attachments == {}
