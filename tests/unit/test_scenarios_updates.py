"""«Windows Update no actualiza» de punta a punta contra un Windows Update simulado."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.domain.support import CheckStatus, Plan, Run, RunStatus
from honey_check.infrastructure.support.tools import updates
from simulated_windows import SimulatedUpdates


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **faults: object
) -> tuple[SupportEngine, SimulatedUpdates]:
    windows = SimulatedUpdates(tmp_path / "Windows", **faults).install(monkeypatch)  # type: ignore[arg-type]
    data = tmp_path / "datos"
    data.mkdir()
    engine = SupportEngine(
        updates.TOOLS, _Journal(), lambda: SupportEnvironment(data, windows, True, None)
    )
    return engine, windows


def _plan(engine: SupportEngine) -> Plan:
    return engine.plan("system.updates", {})


def _run(engine: SupportEngine) -> Run:
    run = engine.start(_plan(engine).id, confirmed=True)
    deadline = time.monotonic() + 20
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return run


def _final(run: Run) -> str:
    assert run.result is not None
    return next(c.detail or "" for c in run.result.checks if c.label == "Windows Update responde")


def test_healthy_update_only_searches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, windows = _setup(tmp_path, monkeypatch)
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert _final(run) == "La búsqueda funcionó: 4 actualizaciones pendientes"
    assert not any(c.startswith(("sc.exe", "dism.exe")) for c in windows.calls)


def test_disabled_service_is_reenabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, services_disabled=True)
    assert "habilitar los servicios" in (_plan(engine).summary or "")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert "sc.exe config wuauserv start= demand" in windows.calls


def test_service_disabled_by_company_policy_is_not_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, services_disabled=True, disabled_by_policy=True)
    plan = _plan(engine)
    services = next(c for c in plan.checks if c.label == "Servicios deshabilitados")
    assert services.status is CheckStatus.FAIL and "directiva" in (services.detail or "")
    _run(engine)
    assert not any(c.startswith("sc.exe config") for c in windows.calls)


def test_missing_files_error_renews_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(
        tmp_path,
        monkeypatch,
        cache_broken=True,
        errors=[(0x80070002, "Actualización acumulativa ficticia")],
    )
    plan = _plan(engine)
    assert "renovar la caché de Windows Update" in (plan.summary or "")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    renamed = sorted(p.name for p in windows.system_root.rglob("*.old-*"))
    assert len(renamed) == 2
    assert renamed[0].startswith("SoftwareDistribution.old-") or renamed[1].startswith(
        "SoftwareDistribution.old-"
    )


def test_cause_found_only_by_searching_is_fixed_with_dism(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, store_corrupt=True)
    # La revisión no ve nada: el código de la búsqueda (0x80073712) lleva a DISM.
    assert (_plan(engine).summary or "").startswith("No se ve una causa")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert any(
        c.startswith("dism.exe /Online /Cleanup-Image /RestoreHealth") for c in windows.calls
    )
    assert any("0x80073712" in entry.text for entry in run.log)


def test_unknown_search_error_is_shown_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, unknown_search_error=0x80240FFF)
    run = _run(engine)
    assert run.status is RunStatus.PARTIAL
    assert run.result is not None
    final = next(c for c in run.result.checks if c.label == "Windows Update responde")
    assert final.status is CheckStatus.FAIL and final.technical == "0x80240FFF"
    assert not any(c.startswith(("dism.exe", "sc.exe stop")) for c in windows.calls)


def test_no_connection_blocks_before_touching_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, online=False)
    plan = _plan(engine)
    assert any(c.label == "Conexión" and c.status is CheckStatus.FAIL for c in plan.checks)
    run = _run(engine)
    assert run.status is RunStatus.FAILED
    assert windows.calls == []


def test_low_disk_space_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, free_gib=3.2)
    plan = _plan(engine)
    space = next(c for c in plan.checks if c.label == "Poco espacio")
    assert space.status is CheckStatus.FAIL and "3.2 GiB" in (space.detail or "")


def test_store_app_errors_are_not_blamed_on_windows_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(
        tmp_path, monkeypatch, errors=[(0x80073D02, "9NKSQGP7F2NH-5319275A.AppFicticia")]
    )
    plan = _plan(engine)
    store = next(c for c in plan.checks if c.label == "Aplicaciones de la Tienda")
    assert store.status is CheckStatus.INFO
    assert (plan.summary or "").startswith("No se ve una causa")


def test_company_update_server_is_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, wsus="http://wsus.ficticio.local:8530")
    plan = _plan(engine)
    wsus = next(c for c in plan.checks if c.label == "Servidor de la empresa (WSUS)")
    assert "wsus.ficticio.local" in (wsus.detail or "")
