"""Procesos de instalación: definiciones versionadas (plantillas o propias) y su ejecución.

La secuencia es regla de aplicación: los pasos se recorren en orden, los hechos u omitidos no se
repiten, un paso manual o un reinicio detiene la ejecución hasta que el técnico lo marque, un paso
obligatorio que falla la detiene, uno opcional que falla queda omitido con su motivo, y la
ejecución termina cuando todos los pasos están hechos u omitidos. Cada cambio se guarda al
instante para poder reanudar.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from honey_check.domain.procedures import (
    TEMPLATES,
    Procedure,
    ProcedureRun,
    ProcedureStep,
    StepKind,
    StepRecord,
    StepState,
)

from .ports import ToolContext

_WAITS_FOR_TECHNICIAN = (StepKind.MANUAL, StepKind.REBOOT)


class ProcedureNotFound(LookupError):
    pass


class ProcedureStore(Protocol):
    def saved(self) -> list[Procedure]:
        """La última versión guardada de cada proceso."""
        ...

    def versions(self, slug: str) -> list[Procedure]: ...

    def save(self, procedure: Procedure) -> Procedure: ...

    def remove(self, slug: str) -> int: ...

    def save_run(self, run: ProcedureRun) -> None: ...

    def run(self, run_id: str) -> ProcedureRun | None: ...

    def runs(self, limit: int) -> list[ProcedureRun]: ...


class StepExecutor(Protocol):
    """Ejecuta un paso automático y dice si se cumplió, con un detalle legible."""

    def execute(self, step: ProcedureStep, ctx: ToolContext) -> tuple[bool, str]: ...


class ProcedureService:
    def __init__(self, store: ProcedureStore) -> None:
        self._store = store

    # --- Definiciones ---------------------------------------------------------------------------

    def catalog(self) -> list[Procedure]:
        saved = {p.slug: p for p in self._store.saved()}
        templates = [t for t in TEMPLATES if t.slug not in saved]
        return sorted([*saved.values(), *templates], key=lambda p: p.name.lower())

    def versions(self, slug: str) -> list[Procedure]:
        versions = self._store.versions(slug)
        if versions:
            return versions
        template = next((t for t in TEMPLATES if t.slug == slug), None)
        if template is None:
            raise ProcedureNotFound(slug)
        return [template]

    def get(self, slug: str, version: int | None = None) -> Procedure:
        versions = self.versions(slug)
        if version is None or version <= 0:
            return versions[0]
        match = next((p for p in versions if p.version == version), None)
        if match is None:
            raise ProcedureNotFound(f"{slug} v{version}")
        return match

    def save(self, document: Mapping[str, Any]) -> Procedure:
        """Valida y guarda como versión nueva: nunca reemplaza una anterior."""
        managed = {"version", "template", "saved_at", "savedAt"}
        procedure = Procedure.model_validate(
            {k: v for k, v in document.items() if k not in managed}
        )
        stamped = procedure.model_copy(update={"template": False, "saved_at": datetime.now(UTC)})
        return self._store.save(stamped)

    def remove(self, slug: str) -> int:
        return self._store.remove(slug)

    # --- Ejecuciones ----------------------------------------------------------------------------

    def run(self, run_id: str) -> ProcedureRun:
        run = self._store.run(run_id)
        if run is None:
            raise ProcedureNotFound(run_id)
        return run

    def runs(self, limit: int = 50) -> list[ProcedureRun]:
        return self._store.runs(limit)

    def procedure_of(self, run: ProcedureRun) -> Procedure:
        return self.get(run.slug, run.version)

    def pending_steps(self, procedure: Procedure, run: ProcedureRun | None) -> list[ProcedureStep]:
        if run is None:
            return list(procedure.steps)
        return [
            s
            for s in procedure.steps
            if run.record(s.id).state not in (StepState.OK, StepState.SKIPPED)
        ]

    def begin(self, procedure: Procedure, device: str | None) -> ProcedureRun:
        now = datetime.now(UTC)
        run = ProcedureRun(
            id=secrets.token_hex(8),
            slug=procedure.slug,
            version=procedure.version,
            name=procedure.name,
            device=device,
            started_at=now,
            updated_at=now,
            steps=[StepRecord(step=s.id) for s in procedure.steps],
        )
        self._store.save_run(run)
        return run

    def advance(
        self,
        run: ProcedureRun,
        executor: StepExecutor,
        ctx: ToolContext,
        *,
        retry_failed: bool = False,
    ) -> ProcedureRun:
        procedure = self.procedure_of(run)
        total = len(procedure.steps)
        for index, step in enumerate(procedure.steps):
            record = run.record(step.id)
            if record.state in (StepState.OK, StepState.SKIPPED):
                continue
            if record.state is StepState.FAILED and not retry_failed:
                break
            ctx.progress(index, total, step.title)
            ctx.info(f"Paso {index + 1}/{total}: {step.title}")
            if step.kind in _WAITS_FOR_TECHNICIAN:
                run = self._set(
                    run,
                    step.id,
                    StepState.WAITING,
                    step.help or "Márquelo como hecho cuando termine",
                )
                break
            try:
                ok, detail = executor.execute(step, ctx)
            except (OSError, ValueError, RuntimeError) as error:
                ok, detail = False, str(error)
            state = (
                StepState.OK if ok else (StepState.SKIPPED if step.optional else StepState.FAILED)
            )
            run = self._set(run, step.id, state, detail)
            if state is StepState.FAILED:
                ctx.error(f"{step.title}: {detail}")
                break
        return self._close(run)

    def mark(self, run_id: str, step_id: str, done: bool, note: str | None) -> ProcedureRun:
        run = self.run(run_id)
        if not any(r.step == step_id for r in run.steps):
            raise ProcedureNotFound(step_id)
        state = StepState.OK if done else StepState.SKIPPED
        run = self._set(run, step_id, state, note or "Marcado por el técnico", by_technician=True)
        return self._close(run)

    def _set(
        self,
        run: ProcedureRun,
        step_id: str,
        state: StepState,
        detail: str | None,
        *,
        by_technician: bool = False,
    ) -> ProcedureRun:
        now = datetime.now(UTC)
        steps = [
            r.model_copy(
                update={"state": state, "detail": detail, "at": now, "by_technician": by_technician}
            )
            if r.step == step_id
            else r
            for r in run.steps
        ]
        run = run.model_copy(update={"steps": steps, "updated_at": now})
        self._store.save_run(run)
        return run

    def _close(self, run: ProcedureRun) -> ProcedureRun:
        finished = all(r.state in (StepState.OK, StepState.SKIPPED) for r in run.steps)
        if finished != run.finished:
            run = run.model_copy(update={"finished": finished})
            self._store.save_run(run)
        return run
