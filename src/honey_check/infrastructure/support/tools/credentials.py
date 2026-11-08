"""Credenciales guardadas (Administrador de credenciales): listar y eliminar sin leer secretos."""

from __future__ import annotations

from typing import Any

from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import ToolContext
from honey_check.domain.support import ColumnKind, Risk, Tone, ToolResult
from honey_check.infrastructure.windows.credentials import (
    PERSIST,
    TYPES,
    delete_credential,
    list_credentials,
)

from ..base import Params, SupportTool, check, col, fact, link, step, table, text, tool
from ..runner import tool_path

CMDKEY = tool_path("cmdkey.exe")


def _list(params: Params, _ctx: ToolContext) -> ToolResult:
    words = [w.lower() for w in str(params.get("filter") or "").split()]
    rows: list[dict[str, Any]] = [
        {
            "id": f"{c.type}|{c.target}",
            "target": c.target,
            "type": c.type,
            "type_label": TYPES.get(c.type, str(c.type)),
            "user": c.user or "",
            "persist": PERSIST.get(c.persist, str(c.persist)),
            "written": c.last_written.isoformat() if c.last_written else None,
        }
        for c in list_credentials()
        if all(w in f"{c.target} {c.user}".lower() for w in words)
    ]
    rows.sort(key=lambda r: r["target"].lower())
    return ToolResult(
        summary=[
            fact("Credenciales guardadas del usuario", len(rows)),
            fact("Contraseñas", "No se leen ni se muestran", Tone.OK),
        ],
        tables=[
            table(
                "credenciales",
                "Credenciales",
                [
                    col("target", "Destino"),
                    col("user", "Usuario"),
                    col("type_label", "Tipo", priority=2),
                    col("persist", "Se guarda en", priority=3),
                    col("written", "Última modificación", ColumnKind.DATE, 3),
                ],
                rows,
                "id",
                actions=[
                    link(
                        "credentials.delete", "Eliminar", Tone.BAD, target="{target}", type="{type}"
                    )
                ],
            )
        ],
    )


list_tool = SupportTool(
    tool(
        "credentials.list",
        "Credenciales",
        "Credenciales guardadas",
        "Lista las credenciales del Administrador de credenciales del usuario (sin mostrar contraseñas).",
        Risk.READ,
        params=[text("filter", "Buscar")],
    ),
    lambda _p, _e: [step("Listar credenciales", "cmdkey /list")],
    _list,
)


def _exists(target: str, type_: int) -> bool:
    return any(c.target == target and c.type == type_ for c in list_credentials())


def _delete(params: Params, ctx: ToolContext) -> ToolResult:
    target, type_ = params["target"], int(params["type"])
    first_that_works(
        ctx,
        [
            Attempt(
                "API CredDelete",
                lambda: delete_credential(target, type_) or not _exists(target, type_),
            ),
            Attempt(
                "cmdkey /delete",
                lambda: ctx.command([CMDKEY, f"/delete:{target}"], timeout_s=30).ok,
            ),
        ],
    )
    gone = not _exists(target, type_)
    return ToolResult(
        checks=[
            check(
                target,
                gone,
                "Eliminada: Windows pedirá la contraseña la próxima vez"
                if gone
                else "Sigue guardada",
            )
        ],
        verified=gone,
    )


delete = SupportTool(
    tool(
        "credentials.delete",
        "Credenciales",
        "Eliminar credencial guardada",
        "Elimina una credencial guardada (útil cuando una contraseña cambió y Windows sigue usando la vieja).",
        Risk.DESTRUCTIVE,
        params=[
            text("target", "Destino", required=True, pattern=r"[^\r\n\x00]{1,512}"),
            text("type", "Tipo", required=True, pattern=r"[1-6]"),
        ],
        hidden=True,
    ),
    lambda p, _e: [step(f"Eliminar {p['target']}", f'cmdkey /delete:"{p["target"]}"')],
    _delete,
    warnings=lambda _p, _e: [
        "La contraseña no se puede respaldar: el usuario deberá escribirla de nuevo."
    ],
)

TOOLS = [list_tool, delete]
