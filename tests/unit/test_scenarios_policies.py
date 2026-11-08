"""«Las directivas no se aplican» de punta a punta contra un dominio simulado: qué diagnostica,
qué arregla y en qué orden, y qué verifica. Ver tests/simulated_windows.py."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.domain.support import CheckStatus, Run, RunStatus
from honey_check.infrastructure.support.tools.policies import TOOLS
from simulated_windows import SimulatedDomain, policy_event


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


def _engine(tmp_path: Path, windows: SimulatedDomain) -> SupportEngine:
    data = tmp_path / "datos"
    data.mkdir(exist_ok=True)
    return SupportEngine(TOOLS, _Journal(), lambda: SupportEnvironment(data, windows, True, None))


def _run(engine: SupportEngine, target: str = "computer") -> Run:
    plan = engine.plan("domain.policies", {"target": target})
    run = engine.start(plan.id, confirmed=True)
    deadline = time.monotonic() + 20
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return run


def _domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **faults: object) -> SimulatedDomain:
    return SimulatedDomain(tmp_path / "Windows", **faults).install(monkeypatch)  # type: ignore[arg-type]


def _statuses(run: Run) -> dict[str, CheckStatus]:
    assert run.result is not None
    return {check.label: check.status for check in run.result.checks}


def test_healthy_domain_only_applies_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch)
    engine = _engine(tmp_path, windows)
    plan = engine.plan("domain.policies", {"target": "computer"})
    assert plan.summary and plan.summary.startswith("No se encontró una causa")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert run.result and run.result.verified
    assert not any(c.startswith(("w32tm", "klist", "nltest.exe /sc_reset")) for c in windows.calls)
    assert _statuses(run)["Windows registró la aplicación"] is CheckStatus.OK


def test_skewed_clock_and_damaged_pol_are_fixed_before_applying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch, clock_offset_s=9 * 60, machine_pol=b"\x00\x00basura")
    engine = _engine(tmp_path, windows)
    plan = engine.plan("domain.policies", {"target": "computer"})
    assert "hora desfasada" in (plan.summary or "")
    assert "Registry.pol de equipo dañado" in (plan.summary or "")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    calls = windows.calls
    # La hora antes que nada: con 9 minutos de diferencia Kerberos rechaza todo lo demás.
    resync = next(i for i, c in enumerate(calls) if c.startswith("w32tm"))
    apply = next(i for i, c in enumerate(calls) if c.startswith("gpupdate"))
    assert resync < apply
    statuses = _statuses(run)
    assert statuses["Registry.pol de equipo"] is CheckStatus.OK
    assert statuses["Directivas de equipo"] is CheckStatus.OK
    damaged = list(windows.machine_pol_path.parent.glob("Registry.pol.dañado-*"))
    assert len(damaged) == 1 and damaged[0].read_bytes() == b"\x00\x00basura"
    backups = list((tmp_path / "datos" / "respaldos").rglob("Registry.pol*"))
    assert backups and backups[0].read_bytes() == b"\x00\x00basura"


def test_broken_secure_channel_is_reset_when_the_machine_account_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch, channel_ok=False)
    run = _run(_engine(tmp_path, windows))
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert any(c.startswith("nltest.exe /sc_reset") for c in windows.calls)
    assert windows.channel_ok


def test_unrepairable_channel_says_to_rejoin_the_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch, channel_ok=False, channel_repairable=False)
    run = _run(_engine(tmp_path, windows))
    assert run.status is RunStatus.PARTIAL
    assert run.result is not None
    channel = next(c for c in run.result.checks if "canal" in c.label.lower())
    assert channel.status is CheckStatus.FAIL
    assert "volver a unirlo al dominio" in (channel.detail or "")


def test_stale_tickets_are_renewed_when_sysvol_does_not_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch, sysvol_ok=False)
    run = _run(_engine(tmp_path, windows))
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert any(c.startswith("klist.exe") for c in windows.calls)


def test_unreachable_controller_blocks_without_touching_the_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch, dc_reachable=False)
    engine = _engine(tmp_path, windows)
    plan = engine.plan("domain.policies", {"target": "computer"})
    blocked = [c for c in plan.checks if c.status is CheckStatus.FAIL]
    assert blocked and blocked[0].fix is not None
    assert "no se pueden aplicar" in (plan.summary or "")
    run = _run(engine)
    assert run.status is RunStatus.FAILED
    assert not any(
        c.startswith(("gpupdate", "w32tm", "nltest.exe /sc_reset")) for c in windows.calls
    )


def test_closed_ports_block_and_point_to_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch, ports_open=False)
    plan = _engine(tmp_path, windows).plan("domain.policies", {"target": "computer"})
    ports = next(c for c in plan.checks if c.label == "Puertos del controlador")
    assert ports.status is CheckStatus.FAIL
    assert "389" in (ports.detail or "") and ports.fix and ports.fix.tool == "network.diagnose"


def test_an_error_left_by_gpupdate_is_reported_with_its_meaning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(
        tmp_path,
        monkeypatch,
        gpupdate_error=(1058, r"No se pudo leer \\ficticio.local\SysVol\...\gpt.ini"),
    )
    run = _run(_engine(tmp_path, windows))
    assert run.status is RunStatus.PARTIAL
    assert run.result is not None
    error = next(c for c in run.result.checks if c.label.startswith("Error de directivas 1058"))
    assert "gpt.ini" in (error.detail or "") and "gpt.ini" in (error.technical or "")


def test_old_errors_before_the_last_success_are_not_blamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = _domain(tmp_path, monkeypatch)
    windows.events = [policy_event(1030, "Error antiguo", windows.last_policy.replace(year=2025))]
    plan = _engine(tmp_path, windows).plan("domain.policies", {"target": "computer"})
    events = next(c for c in plan.checks if c.label == "Errores de directivas")
    assert events.status is CheckStatus.OK
