"""Herramientas de soporte ficticias para probar la interfaz sin tocar el equipo."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from fixtures.devices import all_nodes  # noqa: E402
from honey_check.application.support.context import RunContext
from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import RunRecorder, SupportEnvironment, ToolContext
from honey_check.application.support.procedures import ProcedureService
from honey_check.domain.peripherals import group_devices  # noqa: E402
from honey_check.domain.support import Chart, ChartKind, ColumnKind, Risk, Tone, ToolResult
from honey_check.infrastructure.support.base import (
    SupportTool,
    check,
    choice,
    col,
    fact,
    link,
    multi,
    step,
    table,
    text,
    tool,
)
from honey_check.infrastructure.support.journal import FileRunJournal
from honey_check.infrastructure.support.procedure_store import FileProcedureStore
from honey_check.infrastructure.support.tools import (
    connectivity,
    devices,
    policies,
    printing,
    repair,
    updates,
)

# Windows simulado activo (dominio con fallas); sin él, los comandos responden «correcto».
SIMULATED: list[Any] = []
HOSTILE_FOLDER = '<img src=x onerror="window.__xss=2">carpeta'
REMOVED: list[list[str]] = []
# Estado ficticio que «el equipo» cambia por fuera: la huella de demo.analyze.
DISK_STATE = {"version": 1}


def _analyze(params: Any, ctx: ToolContext) -> ToolResult:
    ctx.progress(1, 2, "Recorriendo carpetas ficticias")
    time.sleep(0.3)
    root = params["path"]
    tree = {
        "name": root,
        "value": 9_000_000,
        "path": root,
        "children": [
            {"name": "Videos", "value": 6_000_000, "path": f"{root}Videos"},
            {"name": HOSTILE_FOLDER, "value": 2_000_000, "path": f"{root}{HOSTILE_FOLDER}"},
            {"name": "Documentos", "value": 1_000_000, "path": f"{root}Documentos"},
        ],
    }
    files = [
        {"path": f"{root}Videos\\grabacion-{i}.mp4", "size": 1_000_000 - i * 1000}
        for i in range(15)
    ]
    return ToolResult(
        summary=[fact("Total", "8,6 MB"), fact("Sin permiso", 0, Tone.OK)],
        checks=[
            check(
                "Espacio libre", False, "Queda poco espacio", fix=link("demo.cleanup", "Limpiar")
            ),
        ],
        charts=[Chart(id="mapa", title="Mapa de carpetas", kind=ChartKind.TREEMAP, data=[tree])],
        tables=[
            table(
                "archivos",
                "Archivos más grandes",
                [col("path", "Archivo", ColumnKind.PATH), col("size", "Tamaño", ColumnKind.BYTES)],
                files,
                "path",
                actions=[link("demo.inspect", "Ver", path="{path}")],
                bulk=link("demo.remove", "Enviar a la Papelera", Tone.BAD),
                selection_param="items",
            )
        ],
    )


def _inspect(params: Any, ctx: ToolContext) -> ToolResult:
    return ToolResult(summary=[fact("Archivo", params["path"])])


def _cleanup(params: Any, ctx: ToolContext) -> ToolResult:
    ctx.command([r"C:\Windows\System32\hostname.exe"], quiet=True)
    return ToolResult(checks=[check("Temporales", True, "Liberados 12 MB")], verified=True)


def _remove(params: Any, ctx: ToolContext) -> ToolResult:
    REMOVED.append(list(params["items"]))
    return ToolResult(
        checks=[check(item, True, "En la Papelera") for item in params["items"]], verified=True
    )


def _slow(params: Any, ctx: ToolContext) -> ToolResult:
    for index in range(100):
        ctx.cancel.raise_if_cancelled()
        ctx.progress(index, 100, f"Paso {index}")
        time.sleep(0.05)
    return ToolResult(verified=True)


TOOLS = [
    SupportTool(
        tool(
            "demo.analyze",
            "Espacio en disco",
            "Analizar espacio (ficticio)",
            "Mapa de carpetas ficticio.",
            Risk.READ,
            params=[text("path", "Unidad o carpeta", required=True, default="C:\\")],
        ),
        lambda p, _e: [step(f"Recorrer {p['path']}", f'dir /s "{p["path"]}"')],
        _analyze,
        state=lambda _p, _e: str(DISK_STATE["version"]),
    ),
    SupportTool(
        tool(
            "demo.inspect",
            "Espacio en disco",
            "Ver archivo",
            "Detalle.",
            Risk.READ,
            params=[text("path", "Ruta", required=True)],
            hidden=True,
            instant=True,
        ),
        lambda _p, _e: [step("Leer")],
        _inspect,
    ),
    SupportTool(
        tool(
            "demo.cleanup",
            "Limpieza",
            "Limpiar temporales (ficticio)",
            "Borra temporales ficticios.",
            Risk.CHANGE,
            params=[choice("scope", "Alcance", [("user", "Usuario"), ("all", "Todo")])],
        ),
        lambda _p, _e: [step("Borrar temporales", "del /q %TEMP%\\*"), step("Comprobar")],
        _cleanup,
        warnings=lambda _p, _e: ["Cierre los programas abiertos."],
        backup="Los archivos van a la Papelera",
    ),
    SupportTool(
        tool(
            "demo.remove",
            "Limpieza",
            "Enviar a la Papelera",
            "Ficticio.",
            Risk.DESTRUCTIVE,
            params=[multi("items", "Elementos")],
            hidden=True,
        ),
        lambda p, _e: [step(f"Papelera: {item}") for item in p["items"]],
        _remove,
    ),
    SupportTool(
        tool(
            "demo.admin",
            "Sistema",
            "Reparar sistema (ficticio)",
            "Requiere administrador.",
            Risk.CHANGE,
            admin=True,
        ),
        lambda _p, _e: [step("Reparar", "sfc /scannow")],
        _cleanup,
    ),
    SupportTool(
        tool("demo.slow", "Sistema", "Tarea larga (ficticia)", "Se puede cancelar.", Risk.CHANGE),
        lambda _p, _e: [step("Esperar")],
        _slow,
    ),
]


# Los ficticios más los solucionadores reales, que corren contra el Windows simulado.
ALL_TOOLS = [
    *TOOLS,
    *policies.TOOLS,
    *connectivity.TOOLS,
    *printing.TOOLS,
    *updates.TOOLS,
    *repair.TOOLS,
    *devices.TOOLS,
]


def demo_support(directory: Path) -> tuple[SupportEngine, ProcedureService]:
    # Los aparatos se leen del árbol ficticio, nunca del equipo donde corren las pruebas.
    devices._live = lambda: group_devices(all_nodes())  # type: ignore[method-assign]  # noqa: SLF001
    data = directory
    procedures = ProcedureService(FileProcedureStore(lambda: data))
    engine = SupportEngine(
        ALL_TOOLS,
        FileRunJournal(lambda: data),
        lambda: SupportEnvironment(data, SIMULATED[0] if SIMULATED else _Runner(), False, None),
        _SameProcessAdmin(),
        sources=printing.SOURCES,
    )
    return engine, procedures


class _SameProcessAdmin:
    """En el navegador de prueba no hay aviso UAC: la acción corre aquí, como en el proceso
    elevado, y su registro se reenvía igual (el protocolo real se prueba en test_elevated_worker)."""

    def execute(
        self, tool_id: str, params: Any, env: SupportEnvironment, recorder: RunRecorder
    ) -> ToolResult:
        target = next(t for t in ALL_TOOLS if t.definition.id == tool_id)
        context = RunContext(replace(env, is_elevated=True), recorder.cancel, "admin", lambda: None)
        result = target.execute(params, context)
        for entry in context.log:
            recorder.record(entry.level, entry.text)
        return result


class _Runner:
    def run(self, args: Any, **_: Any) -> Any:
        from honey_check.application.support.ports import CommandOutput

        return CommandOutput(0, "EQUIPO-FICTICIO", "")
