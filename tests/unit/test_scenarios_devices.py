"""Escenarios con un árbol de dispositivos simulado: quitar restos con respaldo, nunca lo que
está conectado, restaurar desde el respaldo y olvidar un aparato Bluetooth emparejado."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.domain.peripherals import DeviceNode
from honey_check.domain.support import CheckStatus, Run, RunStatus
from honey_check.infrastructure.support.tools import devices
from simulated_windows import SimulatedDevices

OLD = "BBBBBBBB-0000-0000-0000-000000000001"
NOW = "BBBBBBBB-0000-0000-0000-000000000002"
PHONES = "BBBBBBBB-0000-0000-0000-000000000003"
HUB = "USB\\ROOT_HUB30\\4&FICTICIO&0&0"
OLD_RX = "USB\\VID_1A2B&PID_0002\\5&FICTICIO&0&5"
NOW_RX = "USB\\VID_1A2B&PID_0002\\5&FICTICIO&0&4"
BT = "BTHENUM\\DEV_AABBCCDDEEFF\\7&A&0&BLUETOOTHDEVICE_0"


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


def _receiver(usb: str, container: str, present: bool) -> list[DeviceNode]:
    gone = {"present": present, "container_id": container}
    if not present:
        gone["last_removal"] = datetime(2026, 1, 2, tzinfo=UTC)  # type: ignore[assignment]
    return [
        DeviceNode(usb, "Receptor Ficticio", "USB", parent=HUB, driver_inf="oem7.inf", **gone),  # type: ignore[arg-type]
        DeviceNode(usb + "&MI_00", "HID Keyboard Device", "Keyboard", parent=usb, **gone),  # type: ignore[arg-type]
        DeviceNode(usb + "&MI_01", "HID-compliant mouse", "Mouse", parent=usb, **gone),  # type: ignore[arg-type]
    ]


def _tree() -> list[DeviceNode]:
    return [
        *_receiver(OLD_RX, OLD, present=False),
        *_receiver(NOW_RX, NOW, present=True),
        DeviceNode(BT, "Audífonos Ficticios", "Bluetooth", present=False, container_id=PHONES),
    ]


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **faults: object
) -> tuple[SupportEngine, SimulatedDevices]:
    sim = SimulatedDevices(_tree(), **faults).install(monkeypatch)  # type: ignore[arg-type]
    engine = SupportEngine(
        devices.TOOLS, _Journal(), lambda: SupportEnvironment(tmp_path, sim, True, None)
    )
    return engine, sim


def _run(engine: SupportEngine, tool: str, params: dict[str, object]) -> Run:
    run = engine.start(engine.plan(tool, params).id, confirmed=True)
    deadline = time.monotonic() + 20
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return run


def test_review_never_offers_what_is_connected_or_paired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch)
    plan = engine.plan("devices.remove_leftovers", {"devices": [OLD_RX, NOW_RX, BT]})
    marks = {c.label + ("·" + (c.detail or "")): c.status for c in plan.checks}
    assert plan.requires_admin
    assert plan.summary is not None and plan.summary.startswith("Se quitará 1 aparato")
    assert [s for k, s in marks.items() if "conectado ahora" in k] == [CheckStatus.FAIL]
    assert [s for k, s in marks.items() if "Bluetooth" in k] == [CheckStatus.FAIL]


def test_leftover_is_backed_up_removed_and_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, sim = _setup(tmp_path, monkeypatch)
    run = _run(engine, "devices.remove_leftovers", {"devices": [OLD_RX]})
    assert run.status is RunStatus.SUCCEEDED and run.result and run.result.verified
    assert sim.is_present(OLD_RX) is None and sim.is_present(OLD_RX + "&MI_00") is None
    assert sim.is_present(NOW_RX) is True  # el conectado sigue ahí
    # Primero las partes que cuelgan del receptor, después el receptor.
    removed = [c.split(" ", 2)[2] for c in sim.calls if "/remove-device" in c]
    assert removed[-1] == OLD_RX
    backup = next(c for c in run.result.checks if c.label == "Respaldo")
    assert backup.fix is not None and backup.fix.tool == "devices.restore"
    folder = Path(backup.fix.params["backup"])
    assert (folder / "dispositivos.json").is_file()
    assert (folder / "controladores" / "oem7" / "oem7.inf").is_file()

    restored = _run(engine, "devices.restore", {"backup": str(folder)})
    assert restored.status is RunStatus.SUCCEEDED and restored.result
    assert restored.result.verified and sim.installed == ["oem7.inf"]
    assert any(c.detail == "Se reconocerá al conectarlo." for c in restored.result.checks)


def test_a_part_that_will_not_go_is_reported_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, remove_fails={OLD_RX})
    run = _run(engine, "devices.remove_leftovers", {"devices": [OLD_RX + "&MI_01"]})
    assert run.result is not None and not run.result.verified
    result = next(c for c in run.result.checks if c.label == "Receptor Ficticio")
    assert result.status is CheckStatus.FAIL and result.detail is not None
    assert result.detail.startswith("Se quitaron 2 de 3 partes")


def test_paired_bluetooth_is_forgotten_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, sim = _setup(tmp_path, monkeypatch)
    plan = engine.plan("bluetooth.forget", {"devices": [BT]})
    assert plan.summary is not None and "no se puede respaldar" in plan.summary
    run = _run(engine, "bluetooth.forget", {"devices": [BT]})
    assert run.result is not None and run.result.verified
    assert sim.forgotten == ["AA:BB:CC:DD:EE:FF"]
