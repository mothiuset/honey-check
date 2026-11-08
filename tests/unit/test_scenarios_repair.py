"""«Windows dañado» de punta a punta contra DISM, SFC y CBS.log simulados."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.domain.support import CheckStatus, Run, RunStatus
from honey_check.infrastructure.support.tools import repair
from simulated_windows import SimulatedRepair


class _Journal:
    def save(self, run: Run) -> None:
        pass

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return []


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **damage: object
) -> tuple[SupportEngine, SimulatedRepair]:
    windows = SimulatedRepair(tmp_path / "Windows", **damage).install(monkeypatch)  # type: ignore[arg-type]
    engine = SupportEngine(
        repair.TOOLS, _Journal(), lambda: SupportEnvironment(tmp_path, windows, True, None)
    )
    return engine, windows


def _run(engine: SupportEngine) -> Run:
    plan = engine.plan("system.repair", {})
    run = engine.start(plan.id, confirmed=True)
    deadline = time.monotonic() + 20
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return run


def _check(run: Run, label: str) -> tuple[CheckStatus, str]:
    assert run.result is not None
    found = next(c for c in run.result.checks if c.label == label)
    return found.status, found.detail or ""


def _order(windows: SimulatedRepair) -> list[str]:
    return [c.split()[0] for c in windows.calls if c.split()[0] in ("dism.exe", "sfc.exe")]


def test_healthy_windows_runs_sfc_but_not_dism(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch)
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert _check(run, "Archivos del sistema") == (CheckStatus.OK, "No encontró archivos dañados")
    assert _order(windows) == ["sfc.exe"]


def test_live_progress_of_sfc_reaches_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch)
    seen: list[int] = []
    original = repair._live  # noqa: SLF001

    def spy(ctx: object, label: str) -> object:
        feed = original(ctx, label)  # type: ignore[arg-type]

        def wrapped(text: str) -> None:
            feed(text)
            seen.append(ctx.progress_state.done)  # type: ignore[attr-defined]

        return wrapped

    monkeypatch.setattr(repair, "_live", spy)
    _run(engine)
    assert seen == [25, 100]


def test_damaged_store_is_repaired_before_sfc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, store=1)
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert _order(windows) == ["dism.exe", "sfc.exe"]
    assert _check(run, "Almacén de componentes al terminar")[0] is CheckStatus.OK


def test_files_repaired_by_sfc_are_counted_and_ask_for_a_reboot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, damaged_files=3)
    run = _run(engine)
    assert run.status is RunStatus.SUCCEEDED, run.log
    assert _check(run, "Archivos del sistema") == (CheckStatus.OK, "Reparó 3 archivos")
    assert run.result is not None
    assert any(f.label == "Siguiente paso" for f in run.result.summary)


def test_files_sfc_cannot_repair_lead_to_dism_and_a_second_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, unrepairable_files=2)
    run = _run(engine)
    assert _order(windows) == ["sfc.exe", "dism.exe", "sfc.exe"]
    assert _check(run, "Archivos del sistema") == (CheckStatus.FAIL, "No pudo reparar 2 archivos")
    assert _check(run, "Archivos del sistema (segunda pasada)")[0] is CheckStatus.OK
    assert run.result is not None and run.result.verified


def test_dism_without_source_says_what_is_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = _setup(tmp_path, monkeypatch, store=2, dism_has_source=False)
    run = _run(engine)
    status, detail = _check(run, "Reparar el almacén de componentes")
    assert status is CheckStatus.FAIL and "medio de instalación" in detail


def test_pending_reboot_blocks_without_running_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch, reboot_pending=True)
    plan = engine.plan("system.repair", {})
    assert plan.summary == "Hay un reinicio pendiente: reinicie antes de reparar."
    assert plan.checks[0].status is CheckStatus.FAIL
    run = _run(engine)
    assert run.status is RunStatus.FAILED
    assert windows.calls == []


def test_last_sfc_result_is_shown_in_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, windows = _setup(tmp_path, monkeypatch)
    windows.write_cbs("Cannot repair member file x.sys", "Verify complete")
    plan = engine.plan("system.repair", {})
    last = next(c for c in plan.checks if c.label == "Última comprobación")
    assert "no pudo reparar 1 archivo" in (last.detail or "")


def test_rotated_cbs_log_is_read_from_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = SimulatedRepair(tmp_path / "Windows").install(monkeypatch)
    big = repair.cbs_size() + 10_000
    windows.cbs.write_text("", encoding="utf-8")  # rotado: archivo nuevo y vacío
    windows.write_cbs("Repairing corrupted file C:/Windows/System32/a.dll", "Verify complete")
    assert repair.sfc_report(big).repaired == 1
