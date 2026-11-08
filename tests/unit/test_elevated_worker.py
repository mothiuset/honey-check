"""Acción de soporte como administrador en otro proceso: aquí el «proceso» es un hilo con la
misma tubería, autenticación y protocolo; solo falta el aviso UAC, que no se puede automatizar."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from honey_check.application.ports import CancelToken
from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import (
    CommandOutput,
    SupportEnvironment,
    ToolContext,
    UserSession,
)
from honey_check.domain.inventory import Inventory
from honey_check.domain.support import Risk, Run, RunStatus, ToolResult
from honey_check.infrastructure.support import elevated
from honey_check.infrastructure.support.base import SupportTool, check, secret, step, tool
from honey_check.infrastructure.windows.elevation import ElevationCancelled


class FakeRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutput:
        return CommandOutput(0, "", "")


class MemoryJournal:
    def __init__(self) -> None:
        self.runs: list[Run] = []

    def save(self, run: Run) -> None:
        self.runs.append(run)

    def load(self, run_id: str) -> Run | None:
        return None

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        return self.runs[-limit:]


SEEN: dict[str, Any] = {}
RELEASE = threading.Event()


def _admin_change(params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
    SEEN["elevated"] = ctx.env.is_elevated
    SEEN["root"] = ctx.env.data_root
    ctx.info(f"Clave recibida: {params['password']}")
    ctx.progress(1, 2, "mitad")
    deadline = time.monotonic() + 5
    while not RELEASE.is_set() and time.monotonic() < deadline:
        ctx.cancel.raise_if_cancelled()
        time.sleep(0.01)
    return ToolResult(checks=[check("Cambio como administrador", True)], verified=True)


ADMIN_TOOL = SupportTool(
    tool(
        "demo.elevated",
        "Pruebas",
        "Elevada",
        "Necesita administrador",
        Risk.CHANGE,
        admin=True,
        params=[secret("password", "Clave", required=True)],
    ),
    lambda _p, _e: [step("Cambiar como administrador")],
    _admin_change,
)


class _ThreadProcess:
    def __init__(self, thread: threading.Thread) -> None:
        self._thread = thread

    def has_exited(self) -> bool:
        return not self._thread.is_alive()

    def close(self) -> None:
        self._thread.join(5)


def _in_thread(runner: FakeRunner) -> elevated.Launch:
    def environment(
        root: Path, inventory: Inventory | None, user: UserSession | None
    ) -> SupportEnvironment:
        return SupportEnvironment(root, runner, True, inventory, user)

    def launch(arguments: list[str]) -> _ThreadProcess:
        assert arguments[0] == "--support-worker"
        _flag, address, key = arguments
        worker = threading.Thread(
            target=elevated.serve,
            args=(address, key, {ADMIN_TOOL.definition.id: ADMIN_TOOL}, environment),
            daemon=True,
        )
        worker.start()
        return _ThreadProcess(worker)  # type: ignore[return-value]

    return launch  # type: ignore[return-value]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[SupportEngine]:
    RELEASE.clear()
    SEEN.clear()
    runner = FakeRunner()
    support = SupportEngine(
        [ADMIN_TOOL],
        MemoryJournal(),
        lambda: SupportEnvironment(tmp_path, runner, False, None),
        elevated.ElevatedToolRunner(_in_thread(runner)),
    )
    yield support
    RELEASE.set()
    support.shutdown()


def _wait(engine: SupportEngine, run_id: str, timeout_s: float = 15) -> Run:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run = engine.snapshot(run_id)
        if run.status is not RunStatus.RUNNING:
            return run
        time.sleep(0.02)
    raise AssertionError("la ejecución no terminó")


def test_admin_action_runs_in_the_worker_without_restarting(
    engine: SupportEngine, tmp_path: Path
) -> None:
    plan = engine.plan("demo.elevated", {"password": "clave-ficticia"})
    assert plan.requires_admin
    run = engine.start(plan.id, confirmed=True)
    assert run.elevated is True
    RELEASE.set()
    finished = _wait(engine, run.id)
    assert finished.status is RunStatus.SUCCEEDED, finished.log
    assert finished.result is not None
    assert finished.result.checks[0].label == "Cambio como administrador"
    assert {"elevated": True, "root": tmp_path} == SEEN
    texts = [entry.text for entry in finished.log]
    # El registro del proceso elevado llega en vivo y sin el secreto.
    assert "Clave recibida: ••••" in texts
    assert not any("clave-ficticia" in text for text in texts)


def test_cancel_reaches_the_worker(engine: SupportEngine) -> None:
    plan = engine.plan("demo.elevated", {"password": "x"})
    run = engine.start(plan.id, confirmed=True)
    deadline = time.monotonic() + 10
    while "elevated" not in SEEN and time.monotonic() < deadline:
        time.sleep(0.02)
    engine.cancel(run.id)
    assert _wait(engine, run.id).status is RunStatus.CANCELLED


def test_declined_uac_changes_nothing(tmp_path: Path) -> None:
    SEEN.clear()

    def declined(_arguments: list[str]) -> Any:
        raise ElevationCancelled

    support = SupportEngine(
        [ADMIN_TOOL],
        MemoryJournal(),
        lambda: SupportEnvironment(tmp_path, FakeRunner(), False, None),
        elevated.ElevatedToolRunner(declined),
    )
    plan = support.plan("demo.elevated", {"password": "x"})
    finished = _wait(support, support.start(plan.id, confirmed=True).id)
    assert finished.status is RunStatus.CANCELLED
    assert finished.error == "elevation_declined"
    assert "elevated" not in SEEN
