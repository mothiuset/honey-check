"""API HTTP local de solo lectura y exportación, más la interfaz empaquetada."""

from __future__ import annotations

import importlib
import io
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from honey_check.application.device_query import DeviceQuery, DeviceSort
from honey_check.application.ports import DeviceSummary, InventorySummary, StoreWriteError
from honey_check.application.scan import ModuleProgress, ScanAlreadyRunning, ScanProgress
from honey_check.application.service import (
    AlternateDirectoryRejected,
    FolderOutsideData,
    InventoryService,
    NoPendingInventory,
)
from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.procedures import ProcedureService

from .security import SessionGuard, build_gate, cookie_name
from .support_routes import support_routes

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}
_MISSING_UI = (
    "<!doctype html><html lang='es'><meta charset='utf-8'><title>Honey Check</title>"
    "<p>La interfaz de Honey Check no está compilada. Ejecute <code>npm run build</code> en "
    "<code>ui</code>.</p></html>"
).encode()
_INVENTORY_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_DEVICE_KEY = re.compile(r"^[a-z0-9-]{1,64}$")


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_id: str = Field(alias="inventoryId", pattern=r"^[A-Za-z0-9-]{8,64}$")


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(min_length=1, max_length=1024)


class PickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern="^(folder|file)$")
    title: str = Field(default="Elegir", max_length=200)
    filter: str | None = Field(default=None, max_length=300)


class FolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, min_length=1, max_length=1024)


@dataclass
class AppCallbacks:
    open_folder: Callable[[Path], None]
    request_exit: Callable[[], None]
    # True si se lanzó la instancia elevada; False si el técnico canceló el aviso UAC.
    elevate: Callable[[], bool] = lambda: False
    is_elevated: Callable[[], bool | None] = lambda: None
    # Diálogo de Windows para elegir una carpeta o un archivo: (tipo, título, filtro) → ruta.
    pick_path: Callable[[str, str, str | None], str | None] = lambda _k, _t, _f: None


def _interface_root() -> Traversable:
    """En el ejecutable, la interfaz viaja dentro del .exe como zip en memoria; en desarrollo,
    es la carpeta `dist` que deja `npm run build`."""
    try:
        bundle = importlib.import_module("honey_check._bundle")
    except ImportError:
        return resources.files("honey_check.presentation.web").joinpath("dist")
    return zipfile.Path(zipfile.ZipFile(io.BytesIO(bundle.INTERFACE)))


def static_files() -> dict[str, tuple[Traversable, str]]:
    """Lista cerrada de la interfaz compilada: la petición nunca decide qué archivo se sirve."""
    root = _interface_root()
    files: dict[str, tuple[Traversable, str]] = {}

    def walk(folder: Traversable, prefix: str) -> None:
        for entry in folder.iterdir():
            if entry.is_dir():
                walk(entry, f"{prefix}{entry.name}/")
                continue
            media_type = _MEDIA_TYPES.get(Path(entry.name).suffix.lower())
            if media_type:
                files[f"/{prefix}{entry.name}"] = (entry, media_type)

    if root.is_dir():
        walk(root, "")
    index = files.pop("/index.html", None)
    if index:
        files["/"] = index
    return files


class ApiError(Exception):
    def __init__(self, status: int, code: str, reason: str | None = None) -> None:
        self.status = status
        self.code = code
        self.reason = reason


def _module_json(module: ModuleProgress) -> dict[str, Any]:
    return {
        "name": module.name,
        "status": module.status,
        "durationMs": module.duration_ms,
        "issueCount": module.issue_count,
    }


def _progress_json(progress: ScanProgress) -> dict[str, Any]:
    return {
        "state": progress.state.value,
        "scanId": progress.scan_id,
        "startedAt": progress.started_at.isoformat() if progress.started_at else None,
        "finishedAt": progress.finished_at.isoformat() if progress.finished_at else None,
        "completed": progress.completed,
        "total": progress.total,
        "detail": progress.detail,
        "modules": [_module_json(m) for m in progress.modules],
    }


def _summary_json(summary: InventorySummary) -> dict[str, Any]:
    return {
        "id": summary.inventory_id,
        "deviceKey": summary.device_key,
        "sequence": summary.sequence,
        "fileName": summary.path.name,
        "directory": str(summary.path.parent),
        "sizeBytes": summary.size_bytes,
        "collectedAt": summary.collected_at,
        "hostname": summary.hostname,
        "manufacturer": summary.manufacturer,
        "model": summary.model,
        "serialNumber": summary.serial_number,
        "status": summary.status,
        "schemaVersion": summary.schema_version,
        "appVersion": summary.app_version,
        "invalidReason": summary.invalid_reason,
    }


def _device_json(device: DeviceSummary, current_key: str | None) -> dict[str, Any]:
    return {
        "deviceKey": device.device_key,
        "isCurrent": device.device_key == current_key,
        "hostname": device.hostname,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "serialNumber": device.serial_number,
        "deviceType": device.device_type,
        "osName": device.os_name,
        "domain": device.domain,
        "lastStatus": device.last_status,
        "inventoryCount": device.inventory_count,
        "unreadableCount": device.unreadable_count,
        "lastInventoryId": device.last_inventory_id,
        "lastCollectedAt": device.last_collected_at,
        "firstCollectedAt": device.first_collected_at,
    }


def _checked_id(value: str | None) -> str:
    if value is None or not _INVENTORY_ID.match(value):
        raise ApiError(400, "invalid_inventory_id")
    return value


def _rows_json(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "area": row.area,
            "field": row.field,
            "kind": row.kind.value,
            "before": row.before,
            "after": row.after,
            "state": row.state.value,
        }
        for row in rows
    ]


def _checked_device(value: str | None) -> str:
    if value is None or not _DEVICE_KEY.match(value):
        raise ApiError(400, "invalid_device_key")
    return value


def _lookup_error(error: Exception) -> ApiError:
    reason = getattr(error, "reason", None)
    if reason:
        return ApiError(409, "inventory_unreadable", reason)
    return ApiError(404, "inventory_not_found")


def _error_response(error: ApiError) -> JSONResponse:
    body = {"error": error.code}
    if error.reason:
        body["reason"] = error.reason
    return JSONResponse(body, status_code=error.status)


def create_app(
    service: InventoryService,
    guard: SessionGuard,
    bound_port: Callable[[], int],
    app_version: str,
    callbacks: AppCallbacks,
    lookup_errors: tuple[type[Exception], ...],
    support: tuple[SupportEngine, ProcedureService] | None = None,
) -> Starlette:
    def handled(function: Callable[[Request], Any]) -> Callable[[Request], Response]:
        """Convierte el resultado en JSON y los errores previstos en respuestas con código."""

        def endpoint(request: Request) -> Response:
            try:
                result = function(request)
            except ApiError as error:
                return _error_response(error)
            except lookup_errors as error:
                return _error_response(_lookup_error(error))
            return result if isinstance(result, Response) else JSONResponse(result)

        return endpoint

    def health(_: Request) -> dict[str, str]:
        """Sin datos del equipo: solo permite comprobar que este proceso atiende el puerto."""
        return {"status": "ok", "app": "honey-check", "instance": guard.instance_id}

    def authenticate(request: Request) -> Response:
        if not guard.redeem_ticket(request.path_params["ticket"]):
            raise ApiError(401, "invalid_or_used_ticket")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            cookie_name(bound_port()),
            guard.session_token,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    assets = static_files()

    def static_file(request: Request) -> Response:
        if not assets:
            return Response(_MISSING_UI, media_type=_MEDIA_TYPES[".html"])
        entry, media_type = assets[request.url.path]
        return Response(entry.read_bytes(), media_type=media_type)

    def session(_: Request) -> dict[str, str]:
        return {"csrfToken": guard.csrf_token, "appVersion": app_version}

    def status(_: Request) -> dict[str, Any]:
        workspace = service.workspace()
        failure = service.export_failure
        last = service.last_saved
        current = service.current_device
        return {
            "service": "running",
            "appVersion": app_version,
            "isElevated": callbacks.is_elevated(),
            "currentDevice": (
                {
                    "deviceKey": current.device_key,
                    "identityBasis": current.identity_basis,
                    "hostname": current.hostname,
                }
                if current
                else None
            ),
            "workspace": {
                "directory": str(workspace.directory),
                "available": workspace.available,
                "writable": workspace.writable,
            },
            "scan": _progress_json(service.progress()),
            "referenceId": service.reference(),
            "exportFailure": (
                {"reason": failure.reason, "inventoryId": failure.inventory_id} if failure else None
            ),
            "lastSaved": (
                {
                    "id": last.inventory_id,
                    "deviceKey": last.device_key,
                    "sequence": last.sequence,
                    "fileName": last.path.name,
                    "directory": str(last.path.parent),
                }
                if last
                else None
            ),
        }

    def start_scan(_: Request) -> Response:
        # El cuerpo se ignora: no hay forma de pasar consultas o comandos a un análisis.
        try:
            return JSONResponse({"scanId": service.start_scan()}, status_code=202)
        except ScanAlreadyRunning as error:
            raise ApiError(409, "scan_already_running") from error

    def cancel_scan(_: Request) -> dict[str, bool]:
        return {"cancelled": service.cancel_scan()}

    def inventories(request: Request) -> list[dict[str, Any]]:
        raw = request.query_params.get("device")
        device = _checked_device(raw) if raw is not None else None
        return [_summary_json(s) for s in service.history(device)]

    def devices(request: Request) -> dict[str, Any]:
        params = request.query_params

        def text(name: str, limit: int = 200) -> str | None:
            value = params.get(name)
            return value[:limit] if value else None

        def number(name: str, default: int) -> int:
            raw = params.get(name)
            if raw is None:
                return default
            if not raw.isdigit():
                raise ApiError(400, "invalid_parameter", name)
            return int(raw)

        try:
            sort = DeviceSort(params.get("sort", DeviceSort.LAST_ANALYSIS.value))
        except ValueError as error:
            raise ApiError(400, "invalid_parameter", "sort") from error
        page = service.search_devices(
            DeviceQuery(
                text=text("q") or "",
                manufacturer=text("manufacturer"),
                device_type=text("type"),
                os_name=text("os"),
                status=text("status", 20),
                sort=sort,
                descending=params.get("order", "desc") != "asc",
                page=number("page", 1),
                size=number("size", 25),
            )
        )
        current = service.current_device
        key = current.device_key if current else None
        return {
            "items": [_device_json(d, key) for d in page.items],
            "total": page.total,
            "page": page.page,
            "pages": page.pages,
            "size": page.size,
            "facets": {name: [list(v) for v in values] for name, values in page.facets.items()},
            "currentDeviceKey": key,
        }

    def inventory(request: Request) -> dict[str, object]:
        return service.load(_checked_id(request.path_params["inventory_id"])).to_document()

    def inventory_summary(request: Request) -> dict[str, Any]:
        return _summary_json(service.summary(_checked_id(request.path_params["inventory_id"])))

    def delete_inventory(request: Request) -> dict[str, Any]:
        try:
            target = service.delete_inventory(_checked_id(request.path_params["inventory_id"]))
        except StoreWriteError as error:
            raise ApiError(507, "write_failed", str(error)) from error
        return {"deleted": 1, "trash": str(target.parent)}

    def delete_device(request: Request) -> dict[str, Any]:
        try:
            count, target = service.delete_device(
                _checked_device(request.path_params["device_key"])
            )
        except StoreWriteError as error:
            raise ApiError(507, "write_failed", str(error)) from error
        return {"deleted": count, "trash": str(target)}

    def download(request: Request) -> Response:
        path = service.file_of(_checked_id(request.path_params["inventory_id"]))
        return FileResponse(path, media_type="application/json", filename=path.name)

    def icon(request: Request) -> Response:
        path = service.icon_of(
            _checked_id(request.path_params["inventory_id"]), request.path_params["icon_id"]
        )
        return FileResponse(path, media_type="image/png")

    def comparison(request: Request) -> dict[str, Any]:
        base = _checked_id(request.query_params.get("base"))
        target = _checked_id(request.query_params.get("target"))
        result = service.compare(base, target)
        return {
            "baseId": result.base_id,
            "targetId": result.target_id,
            "sameDevice": result.same_device,
            "rows": _rows_json(result.rows),
            "software": _rows_json(result.software),
            "notComparable": result.not_comparable,
        }

    def pending(_: Request) -> dict[str, object]:
        try:
            return service.pending_inventory().to_document()
        except NoPendingInventory as error:
            raise ApiError(404, "no_pending_inventory") from error

    def pending_download(_: Request) -> Response:
        try:
            item = service.pending_inventory()
        except NoPendingInventory as error:
            raise ApiError(404, "no_pending_inventory") from error
        file_name = f"honey-check_{item.collection.inventory_id}.json"
        return Response(
            item.model_dump_json(by_alias=True, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    async def pending_export(request: Request) -> Response:
        try:
            body = ExportRequest.model_validate(json.loads(await request.body()))
        except (ValueError, ValidationError):
            return _error_response(ApiError(422, "invalid_request"))
        # La escritura se hace fuera del bucle de eventos: puede tardar en una USB lenta.
        try:
            saved = await run_in_threadpool(service.export_pending_to, body.directory)
        except NoPendingInventory:
            return _error_response(ApiError(404, "no_pending_inventory"))
        except AlternateDirectoryRejected as error:
            return _error_response(ApiError(400, "directory_rejected", str(error)))
        except StoreWriteError as error:
            return _error_response(ApiError(507, "write_failed", str(error)))
        return JSONResponse(
            {
                "id": saved.inventory_id,
                "fileName": saved.path.name,
                "directory": str(saved.path.parent),
            }
        )

    async def set_reference(request: Request) -> Response:
        try:
            body = ReferenceRequest.model_validate(json.loads(await request.body()))
        except (ValueError, ValidationError):
            return _error_response(ApiError(422, "invalid_request"))
        try:
            await run_in_threadpool(service.set_reference, body.inventory_id)
        except lookup_errors as error:
            return _error_response(_lookup_error(error))
        except StoreWriteError as error:
            return _error_response(ApiError(507, "write_failed", str(error)))
        return JSONResponse({"referenceId": body.inventory_id})

    async def open_folder(request: Request) -> Response:
        # Solo la carpeta de datos o una carpeta dentro de ella; nunca una ruta cualquiera.
        raw = await request.body()
        try:
            body = FolderRequest.model_validate(json.loads(raw) if raw else {})
        except (ValueError, ValidationError):
            return _error_response(ApiError(422, "invalid_request"))
        try:
            folder = await run_in_threadpool(service.folder_in_data, body.path)
            await run_in_threadpool(callbacks.open_folder, folder)
        except FolderOutsideData:
            return _error_response(ApiError(403, "folder_outside_data"))
        except OSError:
            return _error_response(ApiError(409, "folder_unavailable"))
        return Response(status_code=204)

    async def pick_path(request: Request) -> Response:
        # El diálogo de Windows devuelve solo la ruta que el técnico eligió (o nada si canceló).
        raw = await request.body()
        try:
            body = PickRequest.model_validate(json.loads(raw) if raw else {})
        except (ValueError, ValidationError):
            return _error_response(ApiError(422, "invalid_request"))
        path = await run_in_threadpool(callbacks.pick_path, body.kind, body.title, body.filter)
        return JSONResponse({"path": path})

    async def elevate(_: Request) -> Response:
        if callbacks.is_elevated():
            return _error_response(ApiError(409, "already_elevated"))
        # El aviso UAC bloquea hasta que el técnico responde: fuera del bucle de eventos.
        try:
            launched = await run_in_threadpool(callbacks.elevate)
        except OSError:
            return _error_response(ApiError(500, "elevation_failed"))
        if not launched:
            return _error_response(ApiError(409, "elevation_cancelled"))
        return JSONResponse({"status": "restarting"}, status_code=202)

    def request_exit(_: Request) -> Response:
        callbacks.request_exit()
        return JSONResponse({"status": "stopping"}, status_code=202)

    routes = [
        Route("/health", handled(health)),
        Route("/auth/{ticket}", handled(authenticate)),
        *[Route(path, handled(static_file)) for path in (list(assets) or ["/"])],
        Route("/api/session", handled(session)),
        Route("/api/status", handled(status)),
        Route("/api/scans", handled(start_scan), methods=["POST"]),
        Route("/api/scans/current/cancel", handled(cancel_scan), methods=["POST"]),
        Route("/api/inventories", handled(inventories)),
        Route("/api/devices", handled(devices)),
        Route("/api/inventories/{inventory_id}", handled(inventory)),
        Route("/api/inventories/{inventory_id}/summary", handled(inventory_summary)),
        Route(
            "/api/inventories/{inventory_id}/delete", handled(delete_inventory), methods=["POST"]
        ),
        Route("/api/devices/{device_key}/delete", handled(delete_device), methods=["POST"]),
        Route("/api/inventories/{inventory_id}/download", handled(download)),
        Route("/api/inventories/{inventory_id}/icons/{icon_id}", handled(icon)),
        Route("/api/comparison", handled(comparison)),
        Route("/api/pending", handled(pending)),
        Route("/api/pending/download", handled(pending_download)),
        Route("/api/pending/export", pending_export, methods=["POST"]),
        Route("/api/reference", set_reference, methods=["POST"]),
        Route("/api/folder/open", open_folder, methods=["POST"]),
        Route("/api/pick", pick_path, methods=["POST"]),
        Route("/api/elevate", elevate, methods=["POST"]),
        Route("/api/exit", handled(request_exit), methods=["POST"]),
        *(support_routes(*support) if support else []),
    ]

    async def http_error(_: Request, error: Exception) -> Response:
        code = error.status_code if isinstance(error, HTTPException) else 500
        return JSONResponse({"error": "http_error"}, status_code=code)

    return Starlette(
        routes=routes,
        middleware=[Middleware(BaseHTTPMiddleware, dispatch=build_gate(guard, bound_port))],
        exception_handlers={HTTPException: http_error},
    )
