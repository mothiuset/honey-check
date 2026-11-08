"""Adaptador de los procesos de instalación: cómo se cumple cada paso en Windows y su definición
como herramienta. La secuencia y los estados los decide ProcedureService (aplicación)."""

from __future__ import annotations

import socket
import winreg
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from honey_check.application.support.params import validate
from honey_check.application.support.ports import SupportEnvironment, Tool, ToolContext
from honey_check.application.support.procedures import ProcedureService
from honey_check.domain.procedures import Procedure, ProcedureRun, ProcedureStep, StepKind
from honey_check.domain.support import PlanStep, Risk, Tone, ToolResult
from honey_check.infrastructure.windows.crypt32 import StoreLocation, list_certificates

from ..base import Params, SupportTool, choice, col, fact, link, number, step, table, text, tool
from ..runner import tool_path
from ..winops import service_state, split_command_line

MSIEXEC = tool_path("msiexec.exe")
_OK_EXIT = (0, 1641, 3010)
_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def installed_programs() -> list[tuple[str, str]]:
    """Nombre y versión de lo registrado para desinstalar (lectura directa, sin inventario)."""
    found = []
    views = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    )
    for hive, view in views:
        try:
            with winreg.OpenKey(hive, _UNINSTALL, 0, winreg.KEY_READ | view) as root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                            name = winreg.QueryValueEx(key, "DisplayName")[0]
                            try:
                                version = str(winreg.QueryValueEx(key, "DisplayVersion")[0])
                            except OSError:
                                version = ""
                            found.append((str(name), version))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def version_tuple(text_value: str) -> tuple[int, ...]:
    digits = "".join(c if c.isdigit() or c == "." else " " for c in text_value).split()
    return tuple(int(p) for p in digits[0].split(".") if p) if digits else ()


class WindowsStepExecutor:
    """Implementa StepExecutor: instaladores, comprobaciones y herramientas de soporte."""

    def __init__(self, tools: Callable[[], Mapping[str, Tool]]) -> None:
        self._tools = tools

    @staticmethod
    def _installer(env: SupportEnvironment, file: str) -> Path:
        base = (env.data_root / "instaladores").resolve()
        path = (base / file).resolve()
        if base not in path.parents:
            raise ValueError("El instalador debe estar dentro de HoneyCheck-datos\\instaladores")
        return path

    def execute(self, item: ProcedureStep, ctx: ToolContext) -> tuple[bool, str]:
        params = item.params
        handler = {
            StepKind.INSTALL: self._install,
            StepKind.VERIFY_PROGRAM: self._program,
            StepKind.VERIFY_CERTIFICATE: self._certificate,
            StepKind.VERIFY_SERVICE: self._service,
            StepKind.VERIFY_FILE: self._file,
            StepKind.TOOL: self._tool,
            StepKind.COMMAND: self._command,
        }.get(item.kind)
        if handler is None:
            return False, "Este paso lo hace el técnico"
        return handler(params, ctx)

    def _install(self, params: Mapping[str, Any], ctx: ToolContext) -> tuple[bool, str]:
        path = self._installer(ctx.env, str(params.get("file") or ""))
        if not path.is_file():
            return False, f"No está el instalador {path}"
        args = split_command_line(str(params["args"])) if params.get("args") else []
        if path.suffix.lower() == ".msi":
            command = [MSIEXEC, "/i", str(path), "/qn", "/norestart", *args]
        else:
            command = [str(path), *args]
        output = ctx.command(command, timeout_s=3600)
        reboot = " (requiere reiniciar)" if output.exit_code in (1641, 3010) else ""
        return output.exit_code in _OK_EXIT, f"Código de salida {output.exit_code}{reboot}"

    @staticmethod
    def _program(params: Mapping[str, Any], _ctx: ToolContext) -> tuple[bool, str]:
        wanted = str(params.get("name") or "").lower()
        minimum = version_tuple(str(params.get("min_version") or ""))
        matches = [(n, v) for n, v in installed_programs() if wanted and wanted in n.lower()]
        good = [m for m in matches if not minimum or version_tuple(m[1]) >= minimum]
        return bool(good), ", ".join(
            f"{n} {v}" for n, v in (good or matches)[:3]
        ) or "No está instalado"

    @staticmethod
    def _certificate(params: Mapping[str, Any], _ctx: ToolContext) -> tuple[bool, str]:
        wanted = str(params.get("text") or "").lower()
        for location in (StoreLocation.CURRENT_USER, StoreLocation.LOCAL_MACHINE):
            for cert in list_certificates(location, "My"):
                if wanted and wanted in f"{cert.subject} {cert.issuer}".lower():
                    valid = cert.not_after > datetime.now(UTC)
                    return valid, f"{cert.subject} (vence {cert.not_after:%Y-%m-%d})"
        return False, "No se encontró un certificado con ese texto"

    @staticmethod
    def _service(params: Mapping[str, Any], ctx: ToolContext) -> tuple[bool, str]:
        state = service_state(ctx, str(params.get("name") or ""))
        wanted = str(params.get("state") or "Running")
        return state == wanted, f"Estado: {state or 'no existe'}"

    @staticmethod
    def _file(params: Mapping[str, Any], _ctx: ToolContext) -> tuple[bool, str]:
        path = Path(str(params.get("path") or ""))
        return path.exists(), str(path)

    def _tool(self, params: Mapping[str, Any], ctx: ToolContext) -> tuple[bool, str]:
        target = self._tools().get(str(params.get("tool") or ""))
        if target is None:
            return False, f"Herramienta desconocida: {params.get('tool')}"
        if target.definition.requires_admin and not ctx.env.is_elevated:
            return False, "Requiere ejecutar Honey Check como administrador"
        values = validate(target.definition, dict(params.get("tool_params") or {}))
        result = target.execute(values, ctx)
        failed = [c.label for c in result.checks if c.status.value == "fail"]
        return result.verified is not False and not failed, "; ".join(
            failed
        ) or target.definition.title

    @staticmethod
    def _command(params: Mapping[str, Any], ctx: ToolContext) -> tuple[bool, str]:
        args = split_command_line(str(params.get("command") or ""))
        if not args or not Path(args[0]).is_absolute():
            return False, "El comando debe empezar con la ruta completa del programa"
        output = ctx.command(args, timeout_s=float(params.get("timeout") or 600))
        accepted = params.get("exit_codes") or [0]
        return output.exit_code in accepted, f"Código de salida {output.exit_code}"


# --- Definición como herramientas ------------------------------------------------------------------

_STATE_LABELS = {
    "pending": "Pendiente",
    "ok": "Hecho",
    "failed": "Falló",
    "skipped": "Omitido",
    "waiting": "Espera al técnico",
}


def report(procedure: Procedure, run: ProcedureRun) -> ToolResult:
    """Estado de la ejecución en el formato de resultado que la interfaz sabe mostrar."""
    rows = [
        {
            "id": item.id,
            "run": run.id,
            "title": item.title,
            "kind": item.kind.value,
            "state": _STATE_LABELS[run.record(item.id).state.value],
            "detail": run.record(item.id).detail or (item.help or ""),
        }
        for item in procedure.steps
    ]
    done = sum(1 for r in run.steps if r.state.value in ("ok", "skipped"))
    waiting = any(r.state.value == "waiting" for r in run.steps)
    failed = any(r.state.value == "failed" for r in run.steps)
    tone = Tone.OK if run.finished else (Tone.BAD if failed else Tone.WARN)
    if run.finished:
        next_step = "Terminado"
    elif waiting:
        next_step = "Marque el paso manual y continúe"
    elif failed:
        next_step = "Corrija el paso que falló y reintente"
    else:
        next_step = "Continuar"
    title = f"{procedure.name} (v{procedure.version})" if procedure.version else procedure.name
    return ToolResult(
        summary=[
            fact("Proceso", title),
            fact("Avance", f"{done} de {len(run.steps)} pasos", tone),
            fact("Ejecución", run.id),
            fact("Siguiente", next_step),
        ],
        tables=[
            table(
                "pasos",
                "Pasos",
                [
                    col("title", "Paso"),
                    col("state", "Estado"),
                    col("detail", "Detalle", priority=2),
                    col("kind", "Tipo", priority=3),
                ],
                rows,
                "id",
                actions=[
                    link(
                        "procedure.mark",
                        "Marcar como hecho",
                        Tone.OK,
                        run="{run}",
                        step="{id}",
                        state="ok",
                    ),
                    link("procedure.mark", "Omitir", run="{run}", step="{id}", state="skip"),
                ],
            ),
            table(
                "continuar",
                "Continuar",
                [col("run", "Ejecución")],
                [{"run": run.id}],
                "run",
                actions=[
                    link("procedure.run", "Continuar el proceso", run="{run}"),
                    link(
                        "procedure.run",
                        "Reintentar lo que falló",
                        Tone.WARN,
                        run="{run}",
                        retry_failed="yes",
                    ),
                ],
            ),
        ],
        verified=True if run.finished else None,
    )


def _equivalent(item: ProcedureStep) -> str | None:
    params: dict[str, Any] = item.params
    if item.kind is StepKind.INSTALL:
        file, args = str(params.get("file", "")), str(params.get("args", ""))
        if file.lower().endswith(".msi"):
            return f'msiexec /i "instaladores\\{file}" /qn /norestart {args}'.strip()
        return f'"instaladores\\{file}" {args}'.strip()
    if item.kind is StepKind.TOOL:
        return f"Herramienta {params.get('tool')}"
    if item.kind is StepKind.COMMAND:
        return str(params.get("command"))
    if item.kind is StepKind.VERIFY_SERVICE:
        return f"sc query {params.get('name')}"
    return None


def procedure_tools(
    service: ProcedureService, tools: Callable[[], Mapping[str, Tool]]
) -> list[SupportTool]:
    executor = WindowsStepExecutor(tools)

    def plan_steps(params: Params, _env: SupportEnvironment) -> list[PlanStep]:
        run = service.run(params["run"]) if params.get("run") else None
        procedure = (
            service.procedure_of(run)
            if run
            else service.get(params["procedure"], int(params.get("version") or 0) or None)
        )
        return [
            step(
                f"{s.title}{' (opcional)' if s.optional else ''}",
                _equivalent(s),
                "Lo hace el técnico" if s.kind in (StepKind.MANUAL, StepKind.REBOOT) else None,
            )
            for s in service.pending_steps(procedure, run)
        ]

    def run_procedure(params: Params, ctx: ToolContext) -> ToolResult:
        if params.get("run"):
            run = service.run(params["run"])
        else:
            procedure = service.get(params["procedure"], int(params.get("version") or 0) or None)
            run = service.begin(procedure, socket.gethostname())
        run = service.advance(run, executor, ctx, retry_failed=params.get("retry_failed") == "yes")
        return report(service.procedure_of(run), run)

    def mark(params: Params, _ctx: ToolContext) -> ToolResult:
        run = service.mark(
            params["run"], params["step"], params["state"] == "ok", params.get("note")
        )
        return report(service.procedure_of(run), run)

    return [
        SupportTool(
            tool(
                "procedure.run",
                "Procesos de instalación",
                "Ejecutar proceso",
                "Ejecuta los pasos automáticos de un proceso hasta el primer paso manual; se puede continuar después.",
                Risk.CHANGE,
                params=[
                    text("procedure", "Proceso", pattern=r"[a-z0-9][a-z0-9-]{1,62}"),
                    number("version", "Versión (0 = la última)", default=0),
                    text("run", "Ejecución a continuar", pattern=r"[0-9a-f]{16}"),
                    choice("retry_failed", "Reintentar fallidos", [("", "No"), ("yes", "Sí")]),
                ],
                hidden=True,
            ),
            plan_steps,
            run_procedure,
            warnings=lambda _p, _e: [
                "Los instaladores se ejecutan con los argumentos del proceso: revíselos en el plan."
            ],
        ),
        SupportTool(
            tool(
                "procedure.mark",
                "Procesos de instalación",
                "Marcar paso",
                "Marca un paso como hecho u omitido.",
                Risk.READ,
                params=[
                    text("run", "Ejecución", required=True, pattern=r"[0-9a-f]{16}"),
                    text("step", "Paso", required=True, pattern=r"[a-z0-9-]{1,40}"),
                    choice("state", "Estado", [("ok", "Hecho"), ("skip", "Omitido")]),
                    text("note", "Nota"),
                ],
                hidden=True,
            ),
            lambda p, _e: [step(f"Marcar el paso {p['step']}")],
            mark,
        ),
    ]
