"""«La impresora no imprime» de punta a punta contra una impresora simulada."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.domain.support import CheckStatus, Plan, Run, RunStatus
from honey_check.infrastructure.support.tools import printing
from simulated_windows import SimulatedPrinter

NAME = "Oficina Láser (ficticia)"


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **faults: object
) -> tuple[SupportEngine, SimulatedPrinter]:
    printer = SimulatedPrinter(**faults).install(monkeypatch)  # type: ignore[arg-type]
    engine = SupportEngine(
        printing.TOOLS,
        _Journal(),
        lambda: SupportEnvironment(tmp_path, printer, True, None),
        sources=printing.SOURCES,
    )
    return engine, printer


def _plan(engine: SupportEngine, test_page: bool = True) -> Plan:
    return engine.plan("printers.fix", {"printer": NAME, "test_page": test_page})


def _run(engine: SupportEngine, test_page: bool = True) -> Run:
    run = engine.start(_plan(engine, test_page).id, confirmed=True)
    deadline = time.monotonic() + 20
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return run


def test_printers_are_offered_grouped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, _ = _setup(tmp_path, monkeypatch)
    choices = engine.choices("printers")
    assert [(c.label, c.group) for c in choices] == [
        (NAME, "Predeterminada"),
        ("Microsoft Print to PDF", "Virtuales (PDF, OneNote…)"),
    ]


def test_healthy_printer_only_prints_the_test_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, printer = _setup(tmp_path, monkeypatch)
    assert (_plan(engine).summary or "").startswith("No se encontró un problema")
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert printer.test_pages == 1


def test_stopped_spooler_is_started_and_then_the_printer_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, printer = _setup(tmp_path, monkeypatch, spooler_running=False, paused=True)
    plan = _plan(engine)
    assert "iniciar el servicio de impresión" in (plan.summary or "")
    run = _run(engine)
    # Con el servicio en marcha apareció la pausa, y se reanudó en la segunda ronda.
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert printer.spooler_running and not printer.paused


def test_offline_paused_and_stuck_jobs_are_fixed_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, printer = _setup(tmp_path, monkeypatch, offline=True, paused=True, stuck_jobs=3)
    plan = _plan(engine)
    assert plan.summary == (
        "Se va a ponerla en línea, reanudarla y quitar los trabajos atascados. Después se "
        "comprueba de nuevo."
    )
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert not printer.offline and not printer.paused and printer.stuck_jobs == 0
    assert printer.test_pages == 1


def test_jobs_that_cannot_be_removed_offer_emptying_the_whole_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, stuck_jobs=2, jobs_removable=False)
    run = _run(engine)
    assert run.status is RunStatus.PARTIAL
    assert run.result is not None
    failed = next(c for c in run.result.checks if c.label == "Quitar 2 trabajos trabados")
    assert failed.fix and failed.fix.tool == "printers.clear_queue"


def test_paper_jam_is_explained_not_attempted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, printer = _setup(tmp_path, monkeypatch, error_state=8)
    plan = _plan(engine)
    jam = next(c for c in plan.checks if c.label == "Tiene papel atascado")
    assert jam.status is CheckStatus.FAIL
    assert (plan.summary or "").startswith("Tiene papel atascado")
    run = _run(engine)
    assert run.status is RunStatus.PARTIAL
    assert printer.test_pages == 0  # no se imprime una prueba sobre un atasco


def test_unreachable_network_printer_points_to_the_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, reachable=False)
    plan = _plan(engine)
    port = next(c for c in plan.checks if c.label == "Conexión de red")
    assert port.status is CheckStatus.FAIL
    assert "10.0.0.50:9100" in (port.detail or "") and "cambió de dirección IP" in (
        port.detail or ""
    )


def test_missing_printer_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, name="Otra impresora")
    plan = _plan(engine)
    assert any("Ya no está instalada" in (c.detail or "") for c in plan.checks)


def test_stuck_jobs_are_named_in_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, stuck_jobs=1)
    queue = next(c for c in _plan(engine).checks if c.label == "Trabajos atascados")
    assert queue.detail == (
        "1 trabajo trabado bloquea la cola (por ejemplo «Factura 1.pdf»). Se quitan solo esos."
    )
