"""Comparación de inventarios con datos ficticios."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from fakes import FakeAppx, FakeCim, FakeRegistry, make_ports
from fixtures.vendors import ACER, HP
from honey_check.application.ports import RegistryHive, RegistryView
from honey_check.application.scan import ScanCoordinator
from honey_check.composition import default_collectors
from honey_check.domain.compare import RowState, compare_inventories
from honey_check.domain.inventory import Inventory

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def scan(
    rows: dict[str, Any], programs: dict[str, str] | None = None, collectors: Any = None
) -> Inventory:
    registry = FakeRegistry()
    for name, version in (programs or {}).items():
        registry.put(
            RegistryHive.LOCAL_MACHINE,
            RegistryView.BITS_64,
            f"{UNINSTALL}\\{name}",
            {"DisplayName": name, "DisplayVersion": version},
        )
    received: list[Inventory] = []
    coordinator = ScanCoordinator(
        collectors or default_collectors(),
        make_ports(cim=FakeCim(rows), registry=registry, appx=FakeAppx()),
        "0",
        None,
        received.append,
    )
    coordinator.start()
    assert coordinator.wait(30)
    return received[0]


def test_identical_inventories_have_no_changes() -> None:
    first = scan(HP, {"Editor": "1.0"})
    second = scan(HP, {"Editor": "1.0"})
    result = compare_inventories("a", first, "b", second)
    assert result.changes == []
    assert {row.state for row in result.software} == {RowState.SAME}
    assert result.same_device is True
    # Lo igual también se informa, para poder mostrarlo.
    assert any(r.area == "device" and r.field == "model" for r in result.rows)


def software_by_state(result: Any, state: RowState) -> list[tuple[str, str | None, str | None]]:
    return [(r.field, r.before, r.after) for r in result.software if r.state is state]


def test_software_changes() -> None:
    first = scan(HP, {"Editor": "1.0", "Vieja": "2.0", "Estable": "3.0"})
    second = scan(HP, {"Editor": "1.5", "Nueva": "1.0", "Estable": "3.0"})
    result = compare_inventories("a", first, "b", second)
    assert software_by_state(result, RowState.ADDED) == [("Nueva", None, "1.0")]
    assert software_by_state(result, RowState.REMOVED) == [("Vieja", "2.0", None)]
    assert software_by_state(result, RowState.CHANGED) == [("Editor", "1.0", "1.5")]
    assert software_by_state(result, RowState.SAME) == [("Estable", "3.0", "3.0")]


def test_different_device_is_detected() -> None:
    assert compare_inventories("a", scan(HP), "b", scan(ACER)).same_device is False


def test_disk_replacement_is_detected() -> None:
    disks = [
        {**HP["MSFT_PhysicalDisk"][0], "SerialNumber": "SERIE-NUEVA"},
        HP["MSFT_PhysicalDisk"][1],
    ]
    result = compare_inventories("a", scan(HP), "b", scan({**HP, "MSFT_PhysicalDisk": disks}))
    storage = [r for r in result.rows if r.area == "storage"]
    added = next(r for r in storage if r.state is RowState.ADDED)
    assert "SERIE-NUEVA" in (added.after or "")
    assert [r.state for r in storage].count(RowState.REMOVED) == 1
    assert [r.state for r in storage].count(RowState.SAME) == 1


def test_failed_modules_are_not_comparable_instead_of_changed() -> None:
    def failing(ctx: Any) -> BaseModel:
        raise OSError("fallo simulado")

    class Failing:
        name = "software"
        timeout_s = 5.0
        collect = staticmethod(failing)

    without_software = [c for c in default_collectors() if c.name != "software"] + [Failing()]
    result = compare_inventories(
        "a", scan(HP, {"Editor": "1.0"}), "b", scan(HP, collectors=without_software)
    )
    assert "software" in result.not_comparable
    assert result.software == []
