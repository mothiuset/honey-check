"""Motor de soporte: plan sellado, confirmación, permisos, un cambio a la vez y registro."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from honey_check.application.ports import CancelToken
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.engine import (
    ChangeInProgress,
    ConfirmationRequired,
    ElevationRequired,
    PlanNotFound,
    SupportEngine,
    UnknownTool,
)
from honey_check.application.support.params import InvalidParams
from honey_check.application.support.ports import (
    CommandOutput,
    SupportEnvironment,
    ToolContext,
)
from honey_check.domain.support import Risk, Run, RunStatus, ToolResult
from honey_check.infrastructure.support.base import (
    SupportTool,
    check,
    choice,
    fact,
    number,
    secret,
    step,
    text,
    tool,
)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        self.calls.append(list(args))
        return CommandOutput(0, f"salida de {args[0]}", "")


class MemoryJournal:
    def __init__(self) -> None:
        self.runs: list[Run] = []

    def save(self, run: Run) -> None:
        self.runs.append(run)

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return list(reversed(self.runs))[:limit]


def _read(params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
    ctx.command([r"C:\Windows\System32\hostname.exe"])
    return ToolResult(summary=[fact("Equipo", "EQUIPO-FICTICIO")])


GATE = threading.Event()


def _slow_change(params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
    deadline = time.monotonic() + 5
    while not GATE.is_set() and time.monotonic() < deadline:
        ctx.cancel.raise_if_cancelled()
        time.sleep(0.01)
    return ToolResult(checks=[check("Cambio", True)], verified=True)


def _with_secret(params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
    ctx.info(f"usando {params['password']}")
    return ToolResult()


def _broken(params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
    raise ValueError("Primero analice el equipo")


TOOLS = [
    SupportTool(
        tool(
            "demo.read",
            "Pruebas",
            "Leer",
            "Solo lectura",
            Risk.READ,
            params=[
                text("filter", "Buscar", pattern=r"[a-z]*"),
                number("limit", "Límite", default=5),
            ],
        ),
        lambda _p, _e: [step("Leer", "hostname")],
        _read,
    ),
    SupportTool(
        tool("demo.change", "Pruebas", "Cambiar", "Cambio", Risk.CHANGE),
        lambda _p, _e: [step("Cambiar")],
        _slow_change,
    ),
    SupportTool(
        tool("demo.admin", "Pruebas", "Admin", "Requiere administrador", Risk.CHANGE, admin=True),
        lambda _p, _e: [step("Cambiar como administrador")],
        _slow_change,
    ),
    SupportTool(
        tool(
            "demo.secret",
            "Pruebas",
            "Secreto",
            "Usa una contraseña",
            Risk.READ,
            params=[
                secret("password", "Contraseña", required=True),
                choice("mode", "Modo", [("a", "A"), ("b", "B")]),
            ],
        ),
        lambda _p, _e: [step("Usar la contraseña")],
        _with_secret,
    ),
    SupportTool(
        tool("demo.broken", "Pruebas", "Rota", "Falla", Risk.READ),
        lambda _p, _e: [step("Fallar")],
        _broken,
    ),
]


@pytest.fixture
def engine(tmp_path: Path) -> SupportEngine:
    GATE.clear()
    journal = MemoryJournal()
    runner = FakeRunner()
    elevated = {"value": False}

    def environment() -> SupportEnvironment:
        return SupportEnvironment(tmp_path, runner, elevated["value"], None)

    support = SupportEngine(TOOLS, journal, environment)
    support.journal = journal  # type: ignore[attr-defined]
    support.elevated = elevated  # type: ignore[attr-defined]
    yield support
    GATE.set()
    support.shutdown()


def _wait(engine: SupportEngine, run_id: str) -> Run:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = engine.snapshot(run_id)
        if run.status is not RunStatus.RUNNING:
            return run
        time.sleep(0.01)
    raise AssertionError("la ejecución no terminó")


def test_read_tool_runs_without_confirmation_and_is_journaled(engine: SupportEngine) -> None:
    plan = engine.plan("demo.read", {"filter": "abc"})
    assert plan.steps[0].command == "hostname"
    assert plan.params == {"filter": "abc", "limit": 5}
    run = _wait(engine, engine.start(plan.id, confirmed=False).id)
    assert run.status is RunStatus.SUCCEEDED
    assert run.result is not None
    assert run.result.summary[0].value == "EQUIPO-FICTICIO"
    assert any(e.level.value == "command" for e in run.log)
    assert engine.journal.runs[-1].id == run.id  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "params",
    [{"unknown": 1}, {"filter": "ABC"}, {"filter": 3}, {"limit": "5"}, {"limit": True}],
)
def test_invalid_params_are_rejected_before_planning(
    engine: SupportEngine, params: dict[str, Any]
) -> None:
    with pytest.raises(InvalidParams):
        engine.plan("demo.read", params)


def test_unknown_tool(engine: SupportEngine) -> None:
    with pytest.raises(UnknownTool):
        engine.plan("demo.nothing", {})


def test_change_requires_confirmation_and_plan_survives_refusal(engine: SupportEngine) -> None:
    plan = engine.plan("demo.change", {})
    with pytest.raises(ConfirmationRequired):
        engine.start(plan.id, confirmed=False)
    GATE.set()
    run = _wait(engine, engine.start(plan.id, confirmed=True).id)
    assert run.status is RunStatus.SUCCEEDED


def test_confirmed_plan_is_single_use(engine: SupportEngine) -> None:
    GATE.set()
    plan = engine.plan("demo.change", {})
    _wait(engine, engine.start(plan.id, confirmed=True).id)
    with pytest.raises(PlanNotFound):
        engine.start(plan.id, confirmed=True)


def test_admin_tool_is_refused_without_elevation(engine: SupportEngine) -> None:
    plan = engine.plan("demo.admin", {})
    assert plan.requires_admin
    with pytest.raises(ElevationRequired):
        engine.start(plan.id, confirmed=True)
    engine.elevated["value"] = True  # type: ignore[attr-defined]
    GATE.set()
    assert _wait(engine, engine.start(plan.id, confirmed=True).id).elevated is True


def test_only_one_change_at_a_time_but_reads_continue(engine: SupportEngine) -> None:
    engine.elevated["value"] = True  # type: ignore[attr-defined]
    second = engine.plan("demo.admin", {})
    first = engine.start(engine.plan("demo.change", {}).id, confirmed=True)
    with pytest.raises(ChangeInProgress):
        engine.start(second.id, confirmed=True)
    read = _wait(engine, engine.start(engine.plan("demo.read", {}).id, confirmed=False).id)
    assert read.status is RunStatus.SUCCEEDED
    GATE.set()
    assert _wait(engine, first.id).status is RunStatus.SUCCEEDED


def test_cancel_stops_a_running_tool(engine: SupportEngine) -> None:
    run = engine.start(engine.plan("demo.change", {}).id, confirmed=True)
    assert engine.cancel(run.id)
    assert _wait(engine, run.id).status is RunStatus.CANCELLED


def test_secrets_never_reach_plan_log_or_journal(engine: SupportEngine) -> None:
    plan = engine.plan("demo.secret", {"password": "Clave-Ficticia-123", "mode": "a"})
    assert plan.params["password"] == "••••"
    run = _wait(engine, engine.start(plan.id, confirmed=False).id)
    stored = engine.journal.runs[-1].model_dump_json()  # type: ignore[attr-defined]
    assert "Clave-Ficticia-123" not in run.model_dump_json()
    assert "Clave-Ficticia-123" not in stored
    with pytest.raises(InvalidParams):
        engine.plan("demo.secret", {"password": "x", "mode": "z"})


def test_precondition_failure_is_reported_as_failed(engine: SupportEngine) -> None:
    run = _wait(engine, engine.start(engine.plan("demo.broken", {}).id, confirmed=False).id)
    assert run.status is RunStatus.FAILED
    assert run.error == "Primero analice el equipo"


class _Ctx:
    def __init__(self) -> None:
        self.cancel = CancelToken()
        self.messages: list[str] = []

    def info(self, text: str) -> None:
        self.messages.append(text)

    warn = info


def test_first_that_works_falls_back_and_reports_the_way_used() -> None:
    ctx = _Ctx()

    def broken() -> bool:
        raise OSError("API no disponible")

    used = first_that_works(
        ctx,  # type: ignore[arg-type]
        [
            Attempt("API", broken),
            Attempt("Comando falla", lambda: False),
            Attempt("WMI", lambda: True),
        ],
    )
    assert used == "WMI"
    assert any("API no disponible" in m for m in ctx.messages)
    assert first_that_works(ctx, [Attempt("Nada", lambda: False)]) is None  # type: ignore[arg-type]


def test_a_read_result_knows_when_the_machine_changed(tmp_path: Path) -> None:
    from honey_check.infrastructure.support.base import tool

    state = {"value": "a"}
    probe = SupportTool(
        tool("demo.probe", "Sistema", "Consulta con huella", "Ficticia.", Risk.READ),
        lambda _p, _e: [],
        lambda _p, _c: ToolResult(),
        state=lambda _p, _e: state["value"],
    )
    support = SupportEngine(
        [probe], MemoryJournal(), lambda: SupportEnvironment(tmp_path, FakeRunner(), False, None)
    )
    run = support.start(support.plan("demo.probe", {}).id, confirmed=False)
    while support.snapshot(run.id).status is RunStatus.RUNNING:
        time.sleep(0.01)
    assert support.snapshot(run.id).fingerprint == "a"
    assert support.changed(run.id) is False
    state["value"] = "b"
    assert support.changed(run.id) is True
