"""Agregar una impresora con solo su IP: modelo por SNMP y controlador elegido solo.
Modelos y controladores ficticios."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from honey_check.application.ports import CancelToken
from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import CommandOutput, SupportEnvironment
from honey_check.domain.drivers import best_printer_driver, printer_brand
from honey_check.domain.support import CheckStatus, Run, RunStatus
from honey_check.infrastructure.support.tools import printer_drivers as pd

INSTALLED = [
    "Marca Ficticia LaserPro M404-M405 PCL 6",
    "Marca Ficticia LaserPro M404-M405 PS",
    "Otra Marca X9000 PCL6",
    "Microsoft PCL6 Class Driver",
]


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


class _Windows:
    """pnputil, PowerShell y la lista de impresoras, simulados."""

    def __init__(self, installed: list[str]) -> None:
        self.installed = list(installed)
        self.printers: dict[str, str] = {}
        self.calls: list[str] = []

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        line = " ".join(args)
        self.calls.append(line)
        if "Add-PrinterDriver" in line and stdin:
            self.installed.append(stdin.strip())
        elif "Add-Printer " in line and stdin:
            import json

            data = json.loads(stdin)
            if data["driver"] in self.installed:
                self.printers[data["name"]] = data["driver"]
        return CommandOutput(0, "", "")


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Windows:
    sim = _Windows(INSTALLED)
    store_inf = tmp_path / "oem77.inf"
    store_inf.write_text(
        "[Version]\nClass=Printer\n[Manufacturer]\nM = Mod, NTamd64\n[Mod.NTamd64]\n"
        '"Marca Ficticia Color C300 PCL 6" = I, LPTENUM\\FICTICIAC300\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "installed_driver_names", lambda: list(sim.installed))
    monkeypatch.setattr(pd, "store_models", lambda: {"Marca Ficticia Color C300 PCL 6": store_inf})
    monkeypatch.setattr(pd, "port_reachable", lambda _a: True)
    monkeypatch.setattr(pd, "_printer_exists", lambda name: name in sim.printers)
    monkeypatch.setattr(pd, "_wmi_printer", lambda _n, _m: True)
    return sim


def _identity(monkeypatch: pytest.MonkeyPatch, model: str | None) -> None:
    found: dict[str, Any] = {"model": model, "serial": "SERIE-FICTICIA"} if model else {}
    monkeypatch.setattr(pd, "identify", lambda _h: found)


def _engine(tmp_path: Path, sim: _Windows) -> SupportEngine:
    return SupportEngine(
        [pd.add_network],
        _Journal(),
        lambda: SupportEnvironment(tmp_path, sim, True, None),
        sources=pd.SOURCES,
    )


def test_driver_name_follows_the_model_and_brand() -> None:
    # Sin marca conocida se elige igual por el número de modelo.
    assert best_printer_driver("Marca Ficticia LaserPro M404dn", INSTALLED) == INSTALLED[0]
    assert printer_brand("HP LaserJet Pro M404dn") == "hp"
    names = ["HP LaserJet Pro M404-M405 PCL 6", "HP LaserJet Pro M404-M405 PS", "Canon X 404"]
    assert best_printer_driver("HP LaserJet Pro M404dn", names) == "HP LaserJet Pro M404-M405 PCL 6"
    assert best_printer_driver("HP LaserJet Pro M501", names) is None


def test_review_says_which_driver_and_where_it_comes_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: _Windows
) -> None:
    _identity(monkeypatch, "Marca Ficticia Color C300")
    plan = _engine(tmp_path, windows).plan("printers.add_network", {"host": "10.0.0.50"})
    assert plan.summary == (
        "Se agregará «Marca Ficticia Color C300 (10.0.0.50)» en 10.0.0.50 con el controlador "
        "«Marca Ficticia Color C300 PCL 6»."
    )
    detail = next(c.detail for c in plan.checks if c.label == "Controlador")
    assert detail == "«Marca Ficticia Color C300 PCL 6», del almacén de controladores de Windows."


def test_without_snmp_it_warns_and_uses_the_generic_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: _Windows
) -> None:
    _identity(monkeypatch, None)
    plan = _engine(tmp_path, windows).plan("printers.add_network", {"host": "10.0.0.51"})
    marks = {c.label: c.status for c in plan.checks}
    assert marks["Impresora en 10.0.0.51"] is CheckStatus.WARN
    assert marks["Controlador"] is CheckStatus.WARN
    assert "Microsoft PCL6 Class Driver" in (plan.summary or "")


def test_add_installs_the_store_driver_creates_the_printer_and_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: _Windows
) -> None:
    _identity(monkeypatch, "Marca Ficticia Color C300")
    engine = _engine(tmp_path, windows)
    run = engine.start(
        engine.plan("printers.add_network", {"host": "10.0.0.50", "name": "Oficina"}).id,
        confirmed=True,
    )
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        time.sleep(0.02)
    assert run.result is not None and run.result.verified
    assert windows.printers == {"Oficina": "Marca Ficticia Color C300 PCL 6"}
    assert [c.label for c in run.result.checks] == [
        "Controlador",
        "«Oficina» instalada",
        "Página de prueba",
    ]
