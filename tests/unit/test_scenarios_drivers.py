"""Controladores con un Windows simulado: qué falta, instalar desde una carpeta lo que sirve,
reparar y quitar con respaldo. Los .inf y los aparatos son ficticios."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pytest

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.domain.drivers import decode_inf, matches, parse_inf
from honey_check.domain.peripherals import DeviceNode
from honey_check.domain.support import CheckStatus, Run, RunStatus
from honey_check.infrastructure.support.tools import drivers
from simulated_windows import SimulatedDrivers

LECTOR = "PCI\\VEN_1A2B&DEV_0042&SUBSYS_00000000\\3&FICTICIO&0&A0"
CAMARA = "USB\\VID_1A2B&PID_0003\\0001"

INF_LECTOR = """; Controlador ficticio
[Version]
Signature="$Windows NT$"
Class=SDHost
Provider=%Fab%
DriverVer=03/15/2025, 2.1.0.7

[Manufacturer]
%Fab% = Lector, NTamd64, NTarm64

[Lector.NTamd64]
%Desc% = Instalar, PCI\\VEN_1A2B&DEV_0042 ; el de este equipo

[Lector.NTarm64]
%Desc% = Instalar, PCI\\VEN_1A2B&DEV_9999

[Strings]
Fab = "Fabricante Ficticio"
Desc = "Lector de tarjetas ficticio"
"""

INF_AJENO = """[Version]
Class=Net
Provider=Otro
DriverVer=01/01/2024, 1.0
[Manufacturer]
Otro = Red, NTamd64
[Red.NTamd64]
Tarjeta = Instalar, PCI\\VEN_FFFF&DEV_0001
"""


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


def _tree() -> list[DeviceNode]:
    return [
        DeviceNode(
            LECTOR,
            "Dispositivo desconocido",
            None,
            problem_code=28,
            hardware_ids=("PCI\\VEN_1A2B&DEV_0042&SUBSYS_00000000", "PCI\\VEN_1A2B&DEV_0042"),
        ),
        DeviceNode(
            CAMARA,
            "Cámara Ficticia",
            "Camera",
            driver_inf="oem5.inf",
            hardware_ids=("USB\\VID_1A2B&PID_0003",),
        ),
    ]


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **faults: object
) -> tuple[SupportEngine, SimulatedDrivers]:
    sim = SimulatedDrivers(_tree(), tmp_path / "Windows", **faults).install(monkeypatch)  # type: ignore[arg-type]
    (sim.system / "INF" / "oem5.inf").write_text(
        "[Version]\nClass=Camera\nProvider=Ficticio\n[Manufacturer]\nF = Cam, NTamd64\n"
        "[Cam.NTamd64]\nCam = I, USB\\VID_1A2B&PID_0003\n",
        encoding="utf-8",
    )
    engine = SupportEngine(
        drivers.TOOLS, _Journal(), lambda: SupportEnvironment(tmp_path, sim, True, None)
    )
    return engine, sim


def _run(engine: SupportEngine, tool: str, params: dict[str, object]) -> Run:
    run = engine.start(engine.plan(tool, params).id, confirmed=True)
    deadline = time.monotonic() + 20
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return run


def test_inf_is_read_for_this_architecture_only() -> None:
    driver = parse_inf("lector.inf", decode_inf(INF_LECTOR.encode("utf-16")))
    assert driver.hardware_ids == {"PCI\\VEN_1A2B&DEV_0042"}  # la sección ARM64 no cuenta
    assert (driver.provider, driver.version, driver.date) == (
        "Fabricante Ficticio",
        "2.1.0.7",
        date(2025, 3, 15),
    )
    assert driver.description == "Lector de tarjetas ficticio"
    found = matches([driver], _tree())
    assert [(m.device.instance_id, m.rank) for m in found] == [(LECTOR, 0)]  # exacto


def test_missing_driver_is_found_and_says_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch)
    run = _run(engine, "drivers.missing", {})
    assert run.result is not None
    lacking = [c for c in run.result.checks if c.status is CheckStatus.FAIL]
    assert [c.label for c in lacking] == ["Dispositivo desconocido"]
    assert lacking[0].fix is not None and lacking[0].fix.tool == "drivers.install"
    assert "PCI\\VEN_1A2B&DEV_0042&SUBSYS_00000000" in (lacking[0].detail or "")


def test_folder_install_uses_only_what_fits_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, sim = _setup(tmp_path, monkeypatch)
    folder = tmp_path / "Controladores"
    (folder / "lector").mkdir(parents=True)
    (folder / "red").mkdir()
    (folder / "lector" / "lector.inf").write_text(INF_LECTOR, encoding="utf-8")
    (folder / "red" / "red.inf").write_text(INF_AJENO, encoding="utf-8")
    plan = engine.plan("drivers.install", {"path": str(folder)})
    assert plan.summary is not None and plan.summary.startswith(
        "De 2 controladores en la carpeta, 1 sirve para 1 aparato de este equipo"
    )
    run = _run(engine, "drivers.install", {"path": str(folder)})
    assert run.result is not None and run.result.verified
    installs = [c for c in sim.calls if "/add-driver" in c]
    assert len(installs) == 1 and installs[0].endswith("lector.inf /install")
    fixed = run.result.checks[0]
    assert (fixed.status, fixed.detail) == (CheckStatus.OK, "Ya tiene controlador y funciona.")


def test_folder_without_anything_useful_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch)
    folder = tmp_path / "Otros"
    folder.mkdir()
    (folder / "red.inf").write_text(INF_AJENO, encoding="utf-8")
    plan = engine.plan("drivers.install", {"path": str(folder)})
    assert plan.summary is not None and "ninguno sirve" in plan.summary
    # La verificación fallida bloquea el botón: no hay nada que instalar.
    assert [c.status for c in plan.checks] == [CheckStatus.FAIL]


def test_remove_backs_up_first_and_offers_reinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, sim = _setup(tmp_path, monkeypatch)
    plan = engine.plan("drivers.remove", {"inf": "oem5.inf"})
    assert [c.label for c in plan.checks] == ["Cámara Ficticia"]  # lo usa ahora: se avisa
    run = _run(engine, "drivers.remove", {"inf": "oem5.inf"})
    assert run.result is not None and run.result.verified
    assert not (sim.system / "INF" / "oem5.inf").exists()
    saved = next(c for c in run.result.checks if c.label == "Respaldo")
    assert saved.fix is not None and saved.fix.tool == "drivers.install"
    assert list(Path(saved.fix.params["path"]).rglob("oem5.inf"))
