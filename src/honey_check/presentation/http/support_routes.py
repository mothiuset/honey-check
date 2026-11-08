"""API de soporte: catálogo, plan, ejecución supervisada, historial y procesos de instalación."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from honey_check.application.support.engine import (
    ChangeInProgress,
    ConfirmationRequired,
    ElevationRequired,
    PlanNotFound,
    RunNotFound,
    SupportEngine,
    UnknownTool,
)
from honey_check.application.support.params import InvalidParams
from honey_check.application.support.procedures import ProcedureNotFound, ProcedureService


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(pattern=r"^[a-z0-9_.]{1,64}$")
    params: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    plan_id: str = Field(alias="planId", pattern=r"^[0-9a-f]{24}$")
    confirmed: bool = False


_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (InvalidParams, 422, "invalid_params"),
    (UnknownTool, 404, "unknown_tool"),
    (PlanNotFound, 409, "plan_expired"),
    (ConfirmationRequired, 409, "confirmation_required"),
    (ElevationRequired, 403, "elevation_required"),
    (ChangeInProgress, 409, "change_in_progress"),
    (RunNotFound, 404, "run_not_found"),
    (ProcedureNotFound, 404, "procedure_not_found"),
    # Después de las subclases: cualquier otra negativa (clave protegida, de directivas…).
    (PermissionError, 403, "refused"),
)


def _error(status: int, code: str, reason: str | None = None) -> JSONResponse:
    body = {"error": code}
    if reason:
        body["reason"] = reason[:300]
    return JSONResponse(body, status_code=status)


def _dump(model: BaseModel | list[Any]) -> Any:
    if isinstance(model, list):
        return [m.model_dump(mode="json", by_alias=True) for m in model]
    return model.model_dump(mode="json", by_alias=True)


async def _body(request: Request, limit: int = 256 * 1024) -> Any:
    raw = await request.body()
    if len(raw) > limit:
        raise ValueError("cuerpo demasiado grande")
    return json.loads(raw or b"{}")


def _guarded(
    handler: Callable[[Request], Awaitable[Any]],
) -> Callable[[Request], Awaitable[Response]]:
    async def endpoint(request: Request) -> Response:
        try:
            result = await handler(request)
        except (json.JSONDecodeError, ValidationError) as error:
            return _error(422, "invalid_request", str(error).splitlines()[0])
        except ValueError as error:
            for kind, status, code in _ERRORS:
                if isinstance(error, kind):
                    return _error(status, code, str(error))
            return _error(422, "invalid_request", str(error))
        except Exception as error:  # noqa: BLE001 - errores conocidos del motor
            for kind, status, code in _ERRORS:
                if isinstance(error, kind):
                    return _error(status, code, str(error))
            raise
        return result if isinstance(result, Response) else JSONResponse(result)

    return endpoint


def support_routes(engine: SupportEngine, procedures: ProcedureService) -> list[Route]:
    async def tools(_: Request) -> Any:
        return _dump(engine.catalog())

    async def plan(request: Request) -> Any:
        body = PlanRequest.model_validate(await _body(request))
        return _dump(await run_in_threadpool(engine.plan, body.tool, body.params))

    async def start(request: Request) -> Any:
        body = RunRequest.model_validate(await _body(request))
        run = engine.start(body.plan_id, confirmed=body.confirmed)
        return JSONResponse(_dump(run), status_code=202)

    async def source(request: Request) -> Any:
        name = request.path_params["name"]
        return _dump(await run_in_threadpool(engine.choices, name))

    async def runs(request: Request) -> Any:
        # Versiones livianas: sin tablas ni gráficos (pueden ser grandes); se piden por ejecución.
        tool = request.query_params.get("tool")
        if tool is not None and not re.fullmatch(r"[a-z0-9_.]{1,64}", tool):
            raise ValueError("herramienta no válida")
        limit = 30 if tool else 100
        return [
            run.model_copy(
                update={
                    "result": run.result.model_copy(update={"tables": [], "charts": []})
                    if run.result
                    else None,
                    "log": run.log[-5:],
                }
            ).model_dump(mode="json", by_alias=True)
            for run in await run_in_threadpool(engine.history, limit, tool)
        ]

    async def changed(request: Request) -> Any:
        # Si el equipo cambió desde el resultado de una consulta (null: no se puede saber).
        run_id = request.path_params["run_id"]
        return {"changed": await run_in_threadpool(engine.changed, run_id)}

    async def run(request: Request) -> Any:
        run_id = request.path_params["run_id"]
        return _dump(await run_in_threadpool(engine.load, run_id))

    async def cancel(request: Request) -> Any:
        return {"cancelled": engine.cancel(request.path_params["run_id"])}

    async def procedure_catalog(_: Request) -> Any:
        return _dump(procedures.catalog())

    async def procedure_versions(request: Request) -> Any:
        return _dump(procedures.versions(request.path_params["slug"]))

    async def procedure_save(request: Request) -> Any:
        saved = await run_in_threadpool(procedures.save, await _body(request))
        return JSONResponse(_dump(saved), status_code=201)

    async def procedure_remove(request: Request) -> Any:
        return {"removed": await run_in_threadpool(procedures.remove, request.path_params["slug"])}

    async def procedure_runs(_: Request) -> Any:
        return _dump(procedures.runs(50))

    return [
        Route("/api/support/tools", _guarded(tools)),
        Route("/api/support/plans", _guarded(plan), methods=["POST"]),
        Route("/api/support/sources/{name:str}", _guarded(source)),
        Route("/api/support/runs", _guarded(start), methods=["POST"]),
        Route("/api/support/runs", _guarded(runs)),
        Route("/api/support/runs/{run_id:str}", _guarded(run)),
        Route("/api/support/runs/{run_id:str}/cancel", _guarded(cancel), methods=["POST"]),
        Route("/api/support/runs/{run_id:str}/changed", _guarded(changed)),
        Route("/api/procedures", _guarded(procedure_catalog)),
        Route("/api/procedures", _guarded(procedure_save), methods=["POST"]),
        Route("/api/procedures/{slug:str}", _guarded(procedure_versions)),
        Route("/api/procedures/{slug:str}/delete", _guarded(procedure_remove), methods=["POST"]),
        Route("/api/procedure-runs", _guarded(procedure_runs)),
    ]
