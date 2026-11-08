"""«Sin red o sin internet» de punta a punta contra una red simulada: cuál capa es la causa,
qué se corrige y qué se deja dicho porque no depende del equipo."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.domain.support import CheckStatus, Plan, Run, RunStatus
from honey_check.infrastructure.support.tools.connectivity import TOOLS
from simulated_windows import SimulatedNetwork


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **faults: object
) -> tuple[SupportEngine, SimulatedNetwork]:
    network = SimulatedNetwork(**faults).install(monkeypatch)  # type: ignore[arg-type]
    engine = SupportEngine(
        TOOLS, _Journal(), lambda: SupportEnvironment(tmp_path, network, True, None)
    )
    return engine, network


def _plan(engine: SupportEngine) -> Plan:
    return engine.plan("network.connectivity", {})


def _run(engine: SupportEngine) -> Run:
    run = engine.start(_plan(engine).id, confirmed=True)
    deadline = time.monotonic() + 20
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return run


def _status(plan: Plan, label: str) -> CheckStatus:
    return next(c.status for c in plan.checks if c.label == label)


def test_working_connection_needs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, network = _setup(tmp_path, monkeypatch)
    plan = _plan(engine)
    assert plan.summary == "La conexión funciona: hay salida a internet y el DNS responde."
    assert not plan.requires_admin
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED and run.result and run.result.verified
    assert network.calls == []


def test_unplugged_cable_is_the_cause_and_nothing_above_is_blamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, network = _setup(tmp_path, monkeypatch, wifi_connected=False)
    plan = _plan(engine)
    assert _status(plan, "Adaptador de red") is CheckStatus.FAIL
    assert _status(plan, "DNS") is CheckStatus.SKIPPED
    assert "no se arregla desde el equipo" in plan.checks[0].detail.lower()
    run = _run(engine)
    assert run.status is RunStatus.PARTIAL
    assert network.calls == []


def test_disabled_wifi_is_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, network = _setup(tmp_path, monkeypatch, wifi_disabled=True)
    plan = _plan(engine)
    assert "habilitar el adaptador" in (plan.summary or "")
    assert plan.requires_admin
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert any("Enable-NetAdapter" in c for c in network.calls)


def test_dhcp_address_is_renewed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, network = _setup(tmp_path, monkeypatch, has_address=False)
    plan = _plan(engine)
    ip = next(c for c in plan.checks if c.label == "Dirección IP")
    assert "169.254" in (ip.detail or "")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert any(c.startswith("ipconfig.exe /renew Wi-Fi") for c in network.calls)


def test_dhcp_that_never_answers_ends_with_the_cause_still_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, network = _setup(tmp_path, monkeypatch, has_address=False, dhcp_answers=False)
    run = _run(engine)
    assert run.status is RunStatus.PARTIAL
    assert run.result is not None
    ip = next(c for c in run.result.checks if c.label == "Dirección IP")
    assert ip.status is CheckStatus.WARN
    # Se intentó renovar y, al no bastar, reiniciar el adaptador; no se repite sin fin.
    assert sum("ipconfig.exe /renew" in c for c in network.calls) == 1


def test_router_that_recovers_after_restarting_the_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, network = _setup(tmp_path, monkeypatch, router_up=False)
    plan = _plan(engine)
    assert "reiniciar el adaptador" in (plan.summary or "")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert any("Restart-NetAdapter" in c for c in network.calls)


def test_broken_dns_cache_is_flushed_without_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, network = _setup(tmp_path, monkeypatch, dns_cache_broken=True)
    plan = _plan(engine)
    assert "vaciar la caché DNS" in (plan.summary or "")
    assert not plan.requires_admin
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert any(c.startswith("ipconfig.exe /flushdns") for c in network.calls)


def test_dead_dns_server_is_explained_when_internet_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _network = _setup(tmp_path, monkeypatch, dns_server_up=False)
    plan = _plan(engine)
    dns = next(c for c in plan.checks if c.label == "DNS")
    assert dns.status is CheckStatus.FAIL
    assert "192.168.10.1" in (dns.detail or "") and "internet sí funciona" in (dns.detail or "")
    assert _status(plan, "Salida a internet") is CheckStatus.OK


def test_no_upstream_internet_is_not_blamed_on_the_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, network = _setup(tmp_path, monkeypatch, upstream_internet=False)
    plan = _plan(engine)
    internet = next(c for c in plan.checks if c.label == "Salida a internet")
    assert internet.status is CheckStatus.FAIL
    assert "router, proveedor o firewall" in (internet.detail or "")
    assert _status(plan, "Puerta de enlace") is CheckStatus.OK
    run = _run(engine)
    assert run.status is RunStatus.PARTIAL
    assert network.calls == []


def test_unreachable_proxy_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, _network = _setup(
        tmp_path, monkeypatch, proxy=("proxy.ficticio.local", 8080), proxy_up=False
    )
    plan = _plan(engine)
    proxy = next(c for c in plan.checks if c.label == "Proxy")
    assert proxy.status is CheckStatus.FAIL
    assert "proxy.ficticio.local:8080" in (proxy.detail or "")
