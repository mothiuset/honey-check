"""Late workers finish before assembly; all data and ports are fictional."""

import threading
from datetime import datetime
from typing import Any

import pytest
from pydantic import BaseModel

from fakes import make_ports
from honey_check.application.collection import CollectionContext, ModuleFailed
from honey_check.application.ports import CollectionCancelled
from honey_check.application.scan import ScanCoordinator
from honey_check.domain.inventory import Inventory, ModuleStatus, TpmSection
from honey_check.domain.observed import Observed, Reason


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_abandoned_worker_cannot_change_finalized_result_before_assembly(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    monkeypatch.setattr("honey_check.application.scan._POLL_SECONDS", 0.001)
    monkeypatch.setattr("honey_check.application.scan._ABANDON_GRACE_SECONDS", 0.01)
    release = threading.Event()
    worker: list[threading.Thread] = []

    class LateCollector:
        name = "tpm"
        timeout_s = 0.02

        def collect(self, ctx: CollectionContext) -> BaseModel:
            worker.append(threading.current_thread())
            ctx.warn("before", "fictional initial warning")
            ctx.retries = 2
            assert release.wait(3), "supervisor did not reach assembly"
            ctx.warnings[0] = ctx.warnings[0].model_copy(update={"message": "late mutation"})
            ctx.warn("late_warning", "fictional late warning")
            ctx.error("late_error", "fictional late error")
            ctx.retries = 9
            if outcome == "failure":
                raise ModuleFailed("late_failure", "fictional late failure")
            if outcome == "cancelled":
                raise CollectionCancelled
            return TpmSection(
                present=Observed[bool].reported(True, "fictional"),
                spec_version=Observed[str].unknown(Reason.NOT_REPORTED, "fictional"),
                manufacturer=Observed[str].unknown(Reason.NOT_REPORTED, "fictional"),
                firmware_version=Observed[str].unknown(Reason.NOT_REPORTED, "fictional"),
                enabled=Observed[bool].unknown(Reason.NOT_REPORTED, "fictional"),
                activated=Observed[bool].unknown(Reason.NOT_REPORTED, "fictional"),
            )

    class AssemblyBarrier(ScanCoordinator):
        def _assemble(
            self, scan_id: str, runs: list[Any], started_at: datetime, started: float
        ) -> Inventory:
            assert self.snapshot().modules[0].status == "timeout"
            release.set()
            assert worker
            worker[0].join(2)
            assert not worker[0].is_alive()
            return super()._assemble(scan_id, runs, started_at, started)

    received: list[Inventory] = []
    coordinator = AssemblyBarrier([LateCollector()], make_ports(), "0.0.0", None, received.append)
    try:
        coordinator.start()
        assert coordinator.wait(5)
        assert received, coordinator.snapshot().detail
        result = received[0]
        assert result.hardware.tpm is None
        assert result.modules[0].status is ModuleStatus.TIMEOUT
        assert result.modules[0].retries == 2
        assert [w.code for w in result.warnings] == ["before"]
        assert result.warnings[0].message == "fictional initial warning"
        assert [e.code for e in result.errors] == ["module_timeout"]
    finally:
        release.set()
        coordinator.shutdown()
        for thread in worker:
            thread.join(2)
