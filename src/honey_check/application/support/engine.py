"""Motor de herramientas de soporte: plan sellado, confirmación, ejecución supervisada y registro.

Reglas:
- Los parámetros se validan contra la definición; la petición no aporta comandos.
- El plan muestra cada paso y su comando equivalente. Su identificador es el hash del contenido:
  ejecutar exige ese mismo plan, así que lo confirmado es exactamente lo que se hace.
- Un cambio o una acción destructiva exige confirmación.
- La revisión previa dice qué existe, qué está en uso y qué necesita administrador. Lo que lo
  necesita corre en un proceso aparte con el aviso UAC; Honey Check no se reinicia.
- Solo un cambio a la vez; las consultas pueden correr en paralelo.
- Cada ejecución queda registrada en la carpeta de datos, con su log y su resultado.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from honey_check.application.ports import CancelToken, CollectionCancelled
from honey_check.domain.support import (
    Choice,
    ParamKind,
    Plan,
    Risk,
    Run,
    RunStatus,
    ToolDefinition,
    ToolResult,
)

from .context import RunContext
from .params import public_params, validate
from .ports import ElevatedExecutor, ElevationDeclined, RunJournal, SupportEnvironment, Tool

log = logging.getLogger(__name__)

_PLAN_TTL_S = 30 * 60
_MAX_RUNS_IN_MEMORY = 50


class UnknownTool(LookupError):
    pass


class PlanNotFound(LookupError):
    pass


class RunNotFound(LookupError):
    pass


class ConfirmationRequired(PermissionError):
    pass


class ElevationRequired(PermissionError):
    pass


class ChangeInProgress(RuntimeError):
    pass


class _ActiveRun:
    def __init__(self, run: Run, context: RunContext, cancel: CancelToken) -> None:
        self.run = run
        self.context = context
        self.cancel = cancel
        self.thread: threading.Thread | None = None


class SupportEngine:
    def __init__(
        self,
        tools: Sequence[Tool],
        journal: RunJournal,
        environment: Callable[[], SupportEnvironment],
        elevated: ElevatedExecutor | None = None,
        sources: Mapping[str, Callable[[], list[Choice]]] | None = None,
    ) -> None:
        self._tools = {tool.definition.id: tool for tool in tools}
        self._journal = journal
        self._environment = environment
        self._elevated = elevated
        self._sources = dict(sources or {})
        self._lock = threading.Lock()
        self._plans: dict[str, tuple[Plan, dict[str, Any], float]] = {}
        self._runs: dict[str, _ActiveRun] = {}

    # --- Catálogo y plan ---------------------------------------------------------------------

    def catalog(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def choices(self, source: str) -> list[Choice]:
        """Opciones en vivo de un parámetro (por ejemplo, las particiones de cada disco)."""
        provider = self._sources.get(source)
        if provider is None:
            raise UnknownTool(source)
        return provider()

    def _tool(self, tool_id: str) -> Tool:
        tool = self._tools.get(tool_id)
        if tool is None:
            raise UnknownTool(tool_id)
        return tool

    def plan(self, tool_id: str, raw_params: Mapping[str, Any]) -> Plan:
        tool = self._tool(tool_id)
        definition = tool.definition
        values = validate(definition, raw_params)
        prepared = tool.plan(values, self._environment())
        steps = prepared.steps
        shown = public_params(definition, values)
        digest = hashlib.sha256(
            json.dumps(
                {"tool": tool_id, "params": shown, "steps": [s.model_dump() for s in steps]},
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()[:24]
        plan = Plan(
            id=digest,
            tool=tool_id,
            title=definition.title,
            risk=definition.risk,
            requires_admin=definition.requires_admin or prepared.needs_admin,
            action_label=definition.action_label,
            params=shown,
            steps=steps,
            summary=prepared.summary,
            checks=prepared.checks,
            warnings=prepared.warnings,
            backup=prepared.backup,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            now = time.monotonic()
            self._plans = {k: v for k, v in self._plans.items() if now - v[2] < _PLAN_TTL_S}
            self._plans[digest] = (plan, values, now)
        return plan

    # --- Ejecución -------------------------------------------------------------------------------

    def start(self, plan_id: str, *, confirmed: bool) -> Run:
        with self._lock:
            entry = self._plans.get(plan_id)
        if entry is None:
            raise PlanNotFound(plan_id)
        plan, values, _ = entry
        tool = self._tool(plan.tool)
        definition = tool.definition
        environment = self._environment()
        if definition.risk is not Risk.READ and not confirmed:
            raise ConfirmationRequired(plan.tool)
        # Sin permisos, lo que los necesita corre en un proceso de administrador aparte.
        as_worker = plan.requires_admin and not environment.is_elevated
        if as_worker and self._elevated is None:
            raise ElevationRequired(plan.tool)

        run_id = secrets.token_hex(8)
        cancel = CancelToken()
        fingerprint = (
            _fingerprint(tool, values, environment) if definition.risk is Risk.READ else None
        )
        secret_values = [
            str(values[p.name])
            for p in definition.params
            if p.kind is ParamKind.SECRET and values.get(p.name)
        ]
        run = Run(
            id=run_id,
            plan_id=plan_id,
            tool=plan.tool,
            title=plan.title,
            risk=plan.risk,
            params=plan.params,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
            elevated=True if as_worker else environment.is_elevated,
            fingerprint=fingerprint,
        )
        active = _ActiveRun(
            run, RunContext(environment, cancel, run_id, lambda: None, secret_values), cancel
        )
        with self._lock:
            # Comprobar y registrar en el mismo paso: dos cambios simultáneos no pueden pasar.
            if definition.risk is not Risk.READ and any(
                other.run.status is RunStatus.RUNNING and other.run.risk is not Risk.READ
                for other in self._runs.values()
            ):
                raise ChangeInProgress(plan.tool)
            if self._plans.pop(plan_id, None) is None:
                raise PlanNotFound(plan_id)  # otro inicio ya usó este plan
            self._runs[run_id] = active
            self._trim()
        thread = threading.Thread(
            target=self._execute,
            args=(active, tool, values, as_worker),
            name=f"soporte-{plan.tool}",
            daemon=True,
        )
        active.thread = thread
        thread.start()
        return self.snapshot(run_id)

    def _execute(
        self, active: _ActiveRun, tool: Tool, values: dict[str, Any], as_worker: bool
    ) -> None:
        context = active.context
        context.info(f"Inicio: {active.run.title}")
        status = RunStatus.SUCCEEDED
        result: ToolResult | None = None
        error: str | None = None
        try:
            if as_worker and self._elevated is not None:
                context.info("Windows pedirá permiso de administrador para esta acción")
                result = self._elevated.execute(tool.definition.id, values, context.env, context)
            else:
                result = tool.execute(values, context)
            if result.verified is False or any(
                entry.level.value == "error" for entry in context.log
            ):
                status = RunStatus.PARTIAL
        except CollectionCancelled:
            status = RunStatus.CANCELLED
            context.warn("Cancelado por el técnico")
        except ElevationDeclined:
            status = RunStatus.CANCELLED
            error = "elevation_declined"
            context.warn("No se dio permiso de administrador: no cambió nada")
        except (ValueError, PermissionError, LookupError) as failure:
            # Condiciones previas no cumplidas: se explican al técnico sin traza.
            status = RunStatus.FAILED
            error = str(failure) or type(failure).__name__
            context.error(f"No se pudo: {error}")
        except Exception as failure:  # noqa: BLE001 - toda falla queda en el registro de la acción
            status = RunStatus.FAILED
            error = str(failure) or type(failure).__name__
            context.error(f"Falló: {error}")
            log.exception("Herramienta %s falló", tool.definition.id)
        context.info("Fin")
        finished = active.run.model_copy(
            update={
                "status": status,
                "finished_at": datetime.now(UTC),
                "result": result,
                "error": error,
                "log": list(context.log),
                "progress": context.progress_state,
            }
        )
        # Primero al registro y después visible: lo que la interfaz ve terminado ya está guardado.
        try:
            self._journal.save(finished)
        except OSError as failure:
            log.warning("No se pudo registrar la acción: %s", type(failure).__name__)
        with self._lock:
            active.run = finished

    def snapshot(self, run_id: str) -> Run:
        with self._lock:
            active = self._runs.get(run_id)
            if active is None:
                raise RunNotFound(run_id)
            run = active.run
            if run.status is RunStatus.RUNNING:
                run = run.model_copy(
                    update={
                        "log": list(active.context.log),
                        "progress": active.context.progress_state,
                    }
                )
            return run

    def changed(self, run_id: str) -> bool | None:
        """Si el equipo cambió desde el resultado de una consulta (None si no se puede saber)."""
        run = self.load(run_id)
        if run.fingerprint is None or run.status is RunStatus.RUNNING:
            return None
        tool = self._tools.get(run.tool)
        compare = getattr(tool, "changed_since", None)
        if compare is None:
            return None
        try:
            return compare(run.fingerprint, run.params, self._environment())  # type: ignore[no-any-return]
        except Exception as error:  # noqa: BLE001 - sin huella no se avisa, nada más
            log.info("Huella de %s no disponible: %s", run.tool, type(error).__name__)
            return None

    def load(self, run_id: str) -> Run:
        """Una ejecución completa: en memoria si sigue reciente, si no desde el registro."""
        try:
            return self.snapshot(run_id)
        except RunNotFound:
            stored = self._journal.load(run_id)
            if stored is None:
                raise
            return stored

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            active = self._runs.get(run_id)
        if active is None:
            raise RunNotFound(run_id)
        if active.run.status is not RunStatus.RUNNING:
            return False
        active.cancel.cancel()
        return True

    def history(self, limit: int = 100, tool: str | None = None) -> list[Run]:
        with self._lock:
            current = [
                active.run
                for active in self._runs.values()
                if tool is None or active.run.tool == tool
            ]
        stored = self._journal.recent(limit, tool)
        seen = {run.id for run in current}
        runs = current + [run for run in stored if run.id not in seen]
        return sorted(runs, key=lambda r: r.started_at, reverse=True)[:limit]

    def _trim(self) -> None:
        finished = [k for k, v in self._runs.items() if v.run.status is not RunStatus.RUNNING]
        for key in finished[: max(0, len(self._runs) - _MAX_RUNS_IN_MEMORY)]:
            self._runs.pop(key, None)

    def shutdown(self) -> None:
        with self._lock:
            actives = list(self._runs.values())
        for active in actives:
            active.cancel.cancel()
        for active in actives:
            if active.thread is not None:
                active.thread.join(5)


def _fingerprint(tool: Tool, values: dict[str, Any], env: SupportEnvironment) -> str | None:
    """Huella opcional de una consulta (solo algunas herramientas la tienen)."""
    probe = getattr(tool, "fingerprint", None)
    if probe is None:
        return None
    try:
        return probe(values, env)  # type: ignore[no-any-return]
    except Exception as error:  # noqa: BLE001 - sin huella, la consulta corre igual
        log.info("Huella de %s no disponible: %s", tool.definition.id, type(error).__name__)
        return None
