"""Coordinación de un análisis: módulos aislados, límites de tiempo, cancelación y progreso."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from honey_check.domain.identity import device_key
from honey_check.domain.inventory import (
    CollectionInfo,
    CollectionStatus,
    DeviceIdentity,
    HardwareSection,
    Inventory,
    Issue,
    ModuleReport,
    ModuleStatus,
)
from honey_check.domain.observed import Observed, Reason

from .collection import CollectionContext, Collector, ModuleFailed
from .ports import CancelToken, CollectionCancelled, CollectorPorts

log = logging.getLogger(__name__)

_POLL_SECONDS = 0.05
# Tiempo que se espera a un módulo tras cancelarlo antes de abandonar su hilo.
_ABANDON_GRACE_SECONDS = 3.0
_MAX_PARALLEL_MODULES = 6
_HARDWARE_MODULES = (
    "processor",
    "memory",
    "storage",
    "graphics",
    "displays",
    "network",
    "battery",
    "tpm",
)


class ScanState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ScanAlreadyRunning(Exception):
    pass


@dataclass
class ModuleProgress:
    name: str
    status: str = "pending"
    duration_ms: int | None = None
    issue_count: int = 0


@dataclass
class ScanProgress:
    state: ScanState = ScanState.IDLE
    scan_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    modules: list[ModuleProgress] = field(default_factory=list)
    detail: str | None = None

    @property
    def completed(self) -> int:
        return sum(1 for m in self.modules if m.status not in ("pending", "running"))

    @property
    def total(self) -> int:
        return len(self.modules)


@dataclass(frozen=True)
class _ModuleResult:
    section: BaseModel | None
    report: ModuleReport
    warnings: tuple[Issue, ...]
    errors: tuple[Issue, ...]
    attachments: tuple[tuple[str, bytes], ...] = ()


@dataclass
class _ModuleRun:
    collector: Collector
    context: CollectionContext
    thread: threading.Thread | None = None
    started: float = 0.0
    finished: bool = False
    section: BaseModel | None = None
    status: ModuleStatus | None = None
    duration_ms: int = 0
    # Instante en que se ordenó parar; el hilo tiene un margen para terminar.
    stop_requested: float | None = None
    # Lo decide solo el supervisor: el hilo del módulo no puede sobrescribirlo al terminar.
    timed_out: bool = False
    # Only the supervisor publishes this snapshot; abandoned workers retain their own context.
    result: _ModuleResult | None = None


def _sanitized(error: BaseException) -> str:
    """El detalle de una excepción puede arrastrar rutas o seriales: solo se conserva el tipo."""
    return type(error).__name__


class ScanCoordinator:
    def __init__(
        self,
        collectors: Sequence[Collector],
        ports: CollectorPorts,
        app_version: str,
        app_commit: str | None,
        on_finished: Callable[[Inventory], None],
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        max_parallel: int = _MAX_PARALLEL_MODULES,
    ) -> None:
        self._collectors = list(collectors)
        self._ports = ports
        self._version = app_version
        self._commit = app_commit
        self._on_finished = on_finished
        self._clock = clock
        self._max_parallel = max_parallel
        self._lock = threading.Lock()
        self._progress = ScanProgress()
        self._cancel: CancelToken | None = None
        self._supervisor: threading.Thread | None = None

    # --- Interfaz pública ------------------------------------------------------------------------

    def start(self) -> str:
        with self._lock:
            if self._progress.state in (ScanState.RUNNING, ScanState.CANCELLING):
                raise ScanAlreadyRunning
            scan_id = str(uuid.uuid4())
            self._cancel = CancelToken()
            self._progress = ScanProgress(
                state=ScanState.RUNNING,
                scan_id=scan_id,
                started_at=self._clock(),
                modules=[ModuleProgress(c.name) for c in self._collectors],
            )
            self._supervisor = threading.Thread(
                target=self._run, args=(scan_id, self._cancel), name="scan-supervisor", daemon=True
            )
            self._supervisor.start()
        return scan_id

    def cancel(self) -> bool:
        with self._lock:
            if self._progress.state is not ScanState.RUNNING or self._cancel is None:
                return False
            self._progress.state = ScanState.CANCELLING
            self._cancel.cancel()
            return True

    def snapshot(self) -> ScanProgress:
        with self._lock:
            progress = self._progress
            return ScanProgress(
                state=progress.state,
                scan_id=progress.scan_id,
                started_at=progress.started_at,
                finished_at=progress.finished_at,
                modules=[
                    ModuleProgress(m.name, m.status, m.duration_ms, m.issue_count)
                    for m in progress.modules
                ],
                detail=progress.detail,
            )

    def wait(self, timeout_s: float) -> bool:
        supervisor = self._supervisor
        if supervisor is None:
            return True
        supervisor.join(timeout_s)
        return not supervisor.is_alive()

    def shutdown(self, timeout_s: float = 5.0) -> None:
        self.cancel()
        self.wait(timeout_s)

    # --- Supervisión -----------------------------------------------------------------------------

    def _set_module(self, name: str, **changes: Any) -> None:
        with self._lock:
            for module in self._progress.modules:
                if module.name == name:
                    for key, value in changes.items():
                        setattr(module, key, value)

    def _run(self, scan_id: str, cancel: CancelToken) -> None:
        started_at = self._clock()
        started = time.monotonic()
        try:
            runs = self._execute(cancel)
            if cancel.cancelled:
                self._finish(ScanState.CANCELLED, "Análisis cancelado; no se guardó ningún archivo")
                return
            inventory = self._assemble(scan_id, runs, started_at, started)
            self._on_finished(inventory)
            self._finish(ScanState.FINISHED, None)
        except ValidationError as error:
            # El documento completo no cumple el contrato: es preferible no exportarlo.
            log.error("Inventario inválido: %d errores de validación", error.error_count())
            self._finish(ScanState.FAILED, "El resultado no superó la validación del esquema")
        except Exception as error:  # noqa: BLE001 - el supervisor nunca debe morir en silencio
            log.exception("Fallo inesperado del análisis")
            self._finish(ScanState.FAILED, f"Fallo inesperado ({_sanitized(error)})")

    def _finish(self, state: ScanState, detail: str | None) -> None:
        with self._lock:
            self._progress.state = state
            self._progress.detail = detail
            self._progress.finished_at = self._clock()

    def _execute(self, cancel: CancelToken) -> list[_ModuleRun]:
        pending = [
            _ModuleRun(
                collector=collector,
                context=CollectionContext(
                    module=collector.name,
                    ports=self._ports,
                    cancel=CancelToken(parent=cancel),
                    timeout_s=collector.timeout_s,
                ),
            )
            for collector in self._collectors
        ]
        runs = list(pending)
        active: list[_ModuleRun] = []
        while pending or active:
            while pending and len(active) < self._max_parallel:
                if cancel.cancelled:
                    run = pending.pop(0)
                    run.status = ModuleStatus.CANCELLED
                    self._report(run)
                    continue
                run = pending.pop(0)
                self._launch(run)
                active.append(run)
            active = [run for run in active if not self._supervise(run, cancel)]
            time.sleep(_POLL_SECONDS)
        return runs

    def _launch(self, run: _ModuleRun) -> None:
        run.started = time.monotonic()
        self._set_module(run.collector.name, status="running")
        run.thread = threading.Thread(
            target=self._collect, args=(run,), name=f"module-{run.collector.name}", daemon=True
        )
        run.thread.start()

    def _collect(self, run: _ModuleRun) -> None:
        """Cualquier fallo queda dentro del módulo: el resto del análisis continúa."""
        ctx = run.context
        name = run.collector.name
        try:
            section = run.collector.collect(ctx)
            run.section = section
            run.status = (
                ModuleStatus.PARTIAL if ctx.errors or self._has_gaps(ctx) else ModuleStatus.OK
            )
        except CollectionCancelled:
            run.status = ModuleStatus.CANCELLED
        except ModuleFailed as failure:
            ctx.error(failure.code, failure.message, failure.source)
            run.status = ModuleStatus.FAILED
        except ValidationError as error:
            log.warning("Módulo %s: datos inválidos (%d)", name, error.error_count())
            ctx.error("invalid_data", "Los datos del módulo no cumplen el contrato")
            run.status = ModuleStatus.FAILED
        except Exception as error:  # noqa: BLE001 - aislamiento obligatorio entre módulos
            log.exception("Módulo %s: fallo inesperado", name)
            ctx.error("unexpected_error", f"Fallo inesperado ({_sanitized(error)})")
            run.status = ModuleStatus.FAILED
        finally:
            run.duration_ms = int((time.monotonic() - run.started) * 1000)
            run.finished = True

    @staticmethod
    def _has_gaps(ctx: CollectionContext) -> bool:
        return any(w.code == "access_denied" for w in ctx.warnings)

    def _supervise(self, run: _ModuleRun, cancel: CancelToken) -> bool:
        """Devuelve True cuando el módulo ya no necesita supervisión."""
        name = run.collector.name
        now = time.monotonic()
        if run.finished:
            self._report(run)
            return True
        if run.stop_requested is None:
            if cancel.cancelled:
                run.context.cancel.cancel()
                run.stop_requested = now
            elif now - run.started >= run.collector.timeout_s:
                # Se cancela de verdad: el subproceso en curso muere con el token del módulo.
                log.warning("Módulo %s: superó %ss", name, run.collector.timeout_s)
                run.context.cancel.cancel()
                run.stop_requested = now
                run.timed_out = True
            return False
        if now - run.stop_requested >= _ABANDON_GRACE_SECONDS:
            # El hilo es daemon y su resultado tardío se descarta.
            log.warning("Módulo %s: abandonado tras la cancelación", name)
            run.duration_ms = int((now - run.started) * 1000)
            self._report(run)
            return True
        return False

    def _report(self, run: _ModuleRun) -> None:
        if run.result is not None:
            return
        ctx = run.context
        section = run.section
        status = run.status or ModuleStatus.FAILED
        if run.stop_requested is not None:
            # El resultado de un módulo detenido se descarta aunque llegue a terminar.
            section = None
            status = ModuleStatus.TIMEOUT if run.timed_out else ModuleStatus.CANCELLED
        if run.timed_out:
            ctx.error(
                "module_timeout",
                f"El módulo superó el límite de {run.collector.timeout_s:.0f} s",
            )
        result = _ModuleResult(
            section=section,
            report=ModuleReport(
                name=run.collector.name,
                status=status,
                duration_ms=run.duration_ms,
                retries=ctx.retries,
            ),
            warnings=tuple(ctx.warnings),
            errors=tuple(ctx.errors),
            attachments=tuple(ctx.attachments.items()) if section is not None else (),
        )
        run.result = result
        self._set_module(
            run.collector.name,
            status=result.report.status.value,
            duration_ms=result.report.duration_ms,
            issue_count=len(result.errors) + len(result.warnings),
        )

    # --- Ensamblado ------------------------------------------------------------------------------

    def _assemble(
        self, scan_id: str, runs: list[_ModuleRun], started_at: datetime, started: float
    ) -> Inventory:
        results = []
        for run in runs:
            if run.result is None:
                raise RuntimeError("module_not_finalized")
            results.append(run.result)
        sections = {result.report.name: result.section for result in results}
        warnings = [w for result in results for w in result.warnings]
        errors = [e for result in results for e in result.errors]
        reports = [result.report for result in results]
        complete = all(r.status is ModuleStatus.OK for r in reports)
        identity = sections.get("identity")
        key = device_key(identity if isinstance(identity, DeviceIdentity) else None)
        elevated = self._ports.native.is_elevated()
        attachments = {key: data for result in results for key, data in result.attachments}
        return Inventory.model_validate(
            {
                "collection": CollectionInfo(
                    inventory_id=scan_id,
                    started_at=started_at,
                    finished_at=self._clock(),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    app_version=self._version,
                    app_commit=self._commit,
                    status=CollectionStatus.COMPLETE if complete else CollectionStatus.PARTIAL,
                    is_elevated=(
                        Observed[bool].reported(elevated, "native:IsUserAnAdmin")
                        if elevated is not None
                        else Observed[bool].unknown(Reason.NOT_REPORTED, "native:IsUserAnAdmin")
                    ),
                    device_key=key.value,
                    identity_basis=key.basis.value,
                ),
                "device": sections.get("identity"),
                "hardware": HardwareSection.model_validate(
                    {name: sections.get(name) for name in _HARDWARE_MODULES}
                ),
                "operating_system": sections.get("operating_system"),
                "software": sections.get("software"),
                "devices": sections.get("devices"),
                "peripherals": sections.get("peripherals"),
                "security": sections.get("security"),
                "modules": reports,
                "warnings": warnings,
                "errors": errors,
            }
        ).with_attachments(attachments)
