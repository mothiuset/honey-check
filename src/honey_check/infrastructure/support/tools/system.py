"""Sistema: servicios, procesos, inicio, eventos, reparación (SFC, DISM), punto de restauración,
Windows Update, reinicio e informe de batería."""

from __future__ import annotations

import os
import time
import winreg
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from honey_check.application.ports import CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import ToolContext
from honey_check.domain.support import ColumnKind, FileRef, Risk, Tone, ToolResult
from honey_check.infrastructure.windows.com import ComError
from honey_check.infrastructure.windows.wmi import call_method

from ..base import (
    Params,
    SupportTool,
    check,
    choice,
    col,
    fact,
    flag,
    link,
    number,
    step,
    table,
    text,
    tool,
)
from ..runner import tool_path
from ..winops import (
    powershell,
    service_state,
    set_start_mode,
    start_service,
    stop_service,
    wmi_rows,
)

TASKKILL = tool_path("taskkill.exe")
WEVTUTIL = tool_path("wevtutil.exe")
SFC = tool_path("sfc.exe")
DISM = tool_path("Dism.exe")
SHUTDOWN = tool_path("shutdown.exe")
POWERCFG = tool_path("powercfg.exe")
_SERVICE = r"[A-Za-z0-9_.$ -]{1,128}"


# --- Servicios -------------------------------------------------------------------------------------


def _services(params: Params, _ctx: ToolContext) -> ToolResult:
    rows = wmi_rows(
        CimQuery(
            "root/cimv2",
            "Win32_Service",
            ("Name", "DisplayName", "State", "StartMode", "PathName", "StartName"),
        )
    )
    words = [w.lower() for w in str(params.get("filter") or "").split()]
    data = [
        {
            "name": r.get("Name"),
            "display": r.get("DisplayName"),
            "state": r.get("State"),
            "mode": r.get("StartMode"),
            "account": r.get("StartName"),
            "path": r.get("PathName"),
        }
        for r in rows
        if all(w in f"{r.get('Name')} {r.get('DisplayName')}".lower() for w in words)
    ]
    if params.get("problems"):
        data = [d for d in data if d["mode"] == "Auto" and d["state"] != "Running"]
    data.sort(key=lambda d: str(d["display"] or "").lower())
    stopped_auto = sum(1 for d in data if d["mode"] == "Auto" and d["state"] != "Running")
    return ToolResult(
        summary=[
            fact("Servicios", len(data)),
            fact(
                "Automáticos detenidos", stopped_auto, Tone.WARN if stopped_auto else Tone.NEUTRAL
            ),
        ],
        tables=[
            table(
                "servicios",
                "Servicios",
                [
                    col("display", "Servicio"),
                    col("state", "Estado"),
                    col("mode", "Inicio"),
                    col("name", "Nombre", priority=2),
                    col("account", "Cuenta", priority=3),
                    col("path", "Ejecutable", ColumnKind.PATH, 3),
                ],
                data,
                "name",
                actions=[
                    link("services.control", "Iniciar", service="{name}", action="start"),
                    link("services.control", "Detener", Tone.WARN, service="{name}", action="stop"),
                    link("services.control", "Reiniciar", service="{name}", action="restart"),
                ],
            )
        ],
    )


services = SupportTool(
    tool(
        "services.list",
        "Servicios y procesos",
        "Servicios",
        "Lista los servicios con su estado y tipo de inicio; permite iniciarlos, detenerlos o reiniciarlos.",
        Risk.READ,
        params=[text("filter", "Buscar"), flag("problems", "Solo automáticos detenidos")],
    ),
    lambda _p, _e: [step("Listar servicios", "Get-Service")],
    _services,
)

_ACTIONS = [
    ("start", "Iniciar"),
    ("stop", "Detener"),
    ("restart", "Reiniciar"),
    ("auto", "Inicio automático"),
    ("demand", "Inicio manual"),
    ("disabled", "Deshabilitar"),
]


def _control(params: Params, ctx: ToolContext) -> ToolResult:
    name, action = params["service"], params["action"]
    if action == "start":
        ok = start_service(ctx, name)
    elif action == "stop":
        ok = stop_service(ctx, name)
    elif action == "restart":
        ok = stop_service(ctx, name) and start_service(ctx, name)
    else:
        ok = set_start_mode(ctx, name, action)
    return ToolResult(
        summary=[fact("Estado ahora", service_state(ctx, name))],
        checks=[check(dict(_ACTIONS)[action], ok)],
        verified=ok,
    )


control = SupportTool(
    tool(
        "services.control",
        "Servicios y procesos",
        "Controlar un servicio",
        "Inicia, detiene, reinicia o cambia el tipo de inicio de un servicio y verifica el estado final.",
        Risk.CHANGE,
        admin=True,
        params=[
            text("service", "Nombre del servicio", required=True, pattern=_SERVICE),
            choice("action", "Acción", _ACTIONS),
        ],
        hidden=True,
    ),
    lambda p, _e: [
        step(
            f"{dict(_ACTIONS)[p['action']]} {p['service']}",
            f"sc {'config ' + p['service'] + ' start= ' + p['action'] if p['action'] in ('auto', 'demand', 'disabled') else p['action'].replace('restart', 'stop') + ' ' + p['service']}",
        ),
        step("Si falla: WMI Win32_Service y luego PowerShell"),
        step("Verificar el estado final", f"sc query {p['service']}"),
    ],
    _control,
)


# --- Procesos --------------------------------------------------------------------------------------


def _processes(params: Params, _ctx: ToolContext) -> ToolResult:
    rows = wmi_rows(
        CimQuery(
            "root/cimv2",
            "Win32_Process",
            ("ProcessId", "Name", "ExecutablePath", "WorkingSetSize", "ParentProcessId"),
        )
    )
    words = [w.lower() for w in str(params.get("filter") or "").split()]
    data: list[dict[str, Any]] = [
        {
            "pid": r.get("ProcessId"),
            "name": r.get("Name"),
            "memory": r.get("WorkingSetSize") or 0,
            "path": r.get("ExecutablePath") or "",
            "parent": r.get("ParentProcessId"),
        }
        for r in rows
        if all(w in f"{r.get('Name')} {r.get('ExecutablePath')}".lower() for w in words)
    ]
    data.sort(key=lambda d: int(d["memory"] or 0), reverse=True)
    total = sum(int(d["memory"] or 0) for d in data)
    return ToolResult(
        summary=[
            fact("Procesos", len(data)),
            fact("Memoria en uso (conjunto de trabajo)", f"{total / 1024**3:.1f} GiB"),
        ],
        tables=[
            table(
                "procesos",
                "Procesos (por memoria)",
                [
                    col("name", "Proceso"),
                    col("memory", "Memoria", ColumnKind.BYTES),
                    col("pid", "PID", ColumnKind.NUMBER, 2),
                    col("path", "Ejecutable", ColumnKind.PATH, 3),
                ],
                data,
                "pid",
                actions=[link("processes.kill", "Terminar", Tone.BAD, pid="{pid}", name="{name}")],
            )
        ],
    )


processes = SupportTool(
    tool(
        "processes.list",
        "Servicios y procesos",
        "Procesos",
        "Lista los procesos ordenados por memoria; permite terminarlos.",
        Risk.READ,
        params=[text("filter", "Buscar")],
    ),
    lambda _p, _e: [step("Listar procesos", "tasklist /v")],
    _processes,
)


def _alive(pid: int) -> bool:
    try:
        return bool(
            wmi_rows(
                CimQuery("root/cimv2", "Win32_Process", ("ProcessId",), where=f"ProcessId={pid}")
            )
        )
    except OSError:
        return False


def _kill(params: Params, ctx: ToolContext) -> ToolResult:
    pid = int(params["pid"])
    if pid in (0, 4, os.getpid()):
        raise ValueError("Ese proceso no se puede terminar desde aquí")

    def wmi_terminate() -> bool:
        try:
            return (
                call_method("root/cimv2", f'Win32_Process.Handle="{pid}"', "Terminate").get(
                    "ReturnValue"
                )
                == 0
            )
        except (ComError, ValueError):
            return False

    first_that_works(
        ctx,
        [
            Attempt(
                f"taskkill /PID {pid} /T",
                lambda: (
                    ctx.command([TASKKILL, "/PID", str(pid), "/T"], timeout_s=30).ok
                    and not _wait_gone(pid)
                ),
            ),
            Attempt(
                f"taskkill /PID {pid} /T /F",
                lambda: (
                    ctx.command([TASKKILL, "/PID", str(pid), "/T", "/F"], timeout_s=30).ok
                    and not _wait_gone(pid)
                ),
            ),
            Attempt("WMI Win32_Process.Terminate", lambda: wmi_terminate() and not _wait_gone(pid)),
        ],
    )
    gone = not _alive(pid)
    return ToolResult(
        checks=[check(f"{params.get('name') or 'Proceso'} ({pid}) terminado", gone)], verified=gone
    )


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    """True si sigue vivo tras esperar."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return False
        time.sleep(0.5)
    return True


kill = SupportTool(
    tool(
        "processes.kill",
        "Servicios y procesos",
        "Terminar proceso",
        "Cierra un proceso y sus hijos; si no responde, lo fuerza.",
        Risk.DESTRUCTIVE,
        params=[text("pid", "PID", required=True, pattern=r"\d{1,10}"), text("name", "Nombre")],
        hidden=True,
    ),
    lambda p, _e: [
        step("Pedir el cierre", f"taskkill /PID {p['pid']} /T"),
        step("Si no cierra: forzar", f"taskkill /PID {p['pid']} /T /F"),
    ],
    _kill,
    warnings=lambda _p, _e: ["Se pierde el trabajo sin guardar de ese programa."],
)


# --- Inicio ----------------------------------------------------------------------------------------

_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


def _approved_state(hive: int, folder: str, name: str) -> bool | None:
    try:
        with winreg.OpenKey(hive, f"{_APPROVED}\\{folder}", 0, winreg.KEY_READ) as key:
            data, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return bool(data) and data[0] in (2, 6) if isinstance(data, bytes) else None


def _startup_location(location: str) -> tuple[int, str]:
    upper = location.upper()
    hive = (
        winreg.HKEY_LOCAL_MACHINE
        if upper.startswith(("HKLM", "COMMON"))
        else winreg.HKEY_CURRENT_USER
    )
    folder = (
        "StartupFolder"
        if "STARTUP" in upper and not upper.startswith("HK")
        else ("Run32" if "WOW6432NODE" in upper else "Run")
    )
    return hive, folder


def _startup(_params: Params, _ctx: ToolContext) -> ToolResult:
    rows = wmi_rows(
        CimQuery("root/cimv2", "Win32_StartupCommand", ("Name", "Command", "Location", "User"))
    )
    data = []
    for row in rows:
        location = str(row.get("Location") or "")
        hive, folder = _startup_location(location)
        name = str(row.get("Name") or "")
        state = _approved_state(hive, folder, name)
        data.append(
            {
                "id": f"{location}|{name}",
                "name": name,
                "command": row.get("Command"),
                "location": location,
                "user": row.get("User"),
                "enabled": state is not False,
            }
        )
    return ToolResult(
        summary=[
            fact("Programas de inicio", len(data)),
            fact("Desactivados", sum(1 for d in data if not d["enabled"])),
        ],
        tables=[
            table(
                "inicio",
                "Programas que arrancan con Windows",
                [
                    col("name", "Programa"),
                    col("enabled", "Activo", ColumnKind.BOOL),
                    col("location", "Origen", priority=2),
                    col("user", "Usuario", priority=3),
                    col("command", "Comando", ColumnKind.PATH, 3),
                ],
                data,
                "id",
                actions=[
                    link(
                        "startup.toggle",
                        "Desactivar",
                        Tone.WARN,
                        location="{location}",
                        name="{name}",
                        enable="no",
                    ),
                    link(
                        "startup.toggle",
                        "Activar",
                        location="{location}",
                        name="{name}",
                        enable="yes",
                    ),
                ],
            )
        ],
    )


startup = SupportTool(
    tool(
        "startup.list",
        "Servicios y procesos",
        "Programas de inicio",
        "Lista lo que arranca con Windows y permite desactivarlo como el Administrador de tareas (reversible).",
        Risk.READ,
    ),
    lambda _p, _e: [step("Leer los programas de inicio", "wmic startup get caption,command")],
    _startup,
)


def _toggle(params: Params, ctx: ToolContext) -> ToolResult:
    hive, folder = _startup_location(params["location"])
    if hive == winreg.HKEY_LOCAL_MACHINE and not ctx.env.is_elevated:
        raise PermissionError("Es un programa de inicio de todo el equipo: requiere administrador")
    enable = params["enable"] == "yes"
    value = bytes([2 if enable else 3]) + bytes(11)
    with winreg.CreateKeyEx(hive, f"{_APPROVED}\\{folder}", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, params["name"], 0, winreg.REG_BINARY, value)
    state = _approved_state(hive, folder, params["name"])
    ok = state is enable
    return ToolResult(
        checks=[
            check(
                f"{params['name']} {'activado' if enable else 'desactivado'}",
                ok,
                "Surte efecto en el próximo inicio de sesión",
            )
        ],
        verified=ok,
    )


toggle = SupportTool(
    tool(
        "startup.toggle",
        "Servicios y procesos",
        "Activar o desactivar un programa de inicio",
        "Marca el programa como activo o inactivo en el inicio, igual que el Administrador de tareas.",
        Risk.CHANGE,
        params=[
            text("location", "Origen", required=True),
            text("name", "Programa", required=True),
            choice("enable", "Estado", [("no", "Desactivar"), ("yes", "Activar")]),
        ],
        hidden=True,
    ),
    lambda p, _e: [
        step(
            f"{'Activar' if p['enable'] == 'yes' else 'Desactivar'} {p['name']} en StartupApproved",
            "Administrador de tareas > Inicio",
        )
    ],
    _toggle,
)


# --- Eventos ---------------------------------------------------------------------------------------

_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
_LEVELS = {"1": "Crítico", "2": "Error", "3": "Advertencia"}


def _events(params: Params, ctx: ToolContext) -> ToolResult:
    hours = int(params["hours"])
    levels = "Level=1 or Level=2" + (" or Level=3" if params.get("warnings") else "")
    query = f"*[System[({levels}) and TimeCreated[timediff(@SystemTime) <= {hours * 3_600_000}]]]"
    rows = []
    for log_name in ("System", "Application"):
        output = ctx.command(
            [WEVTUTIL, "qe", log_name, f"/q:{query}", "/c:200", "/rd:true", "/f:RenderedXml"],
            timeout_s=90,
            quiet=True,
        )
        if not output.ok:
            ctx.warn(f"No se pudo leer el registro {log_name}")
            continue
        try:
            # Salida de wevtutil: sin DTD ni entidades (se rechazan), así no hay expansión posible.
            if "<!DOCTYPE" in output.stdout or "<!ENTITY" in output.stdout:
                raise ET.ParseError("DTD no permitida")
            root = ET.fromstring(f"<r>{output.stdout}</r>")  # noqa: S314
        except ET.ParseError:
            ctx.warn(f"Registro {log_name} ilegible")
            continue
        for event in root.findall("e:Event", _NS):
            system = event.find("e:System", _NS)
            if system is None:
                continue
            provider = system.find("e:Provider", _NS)
            created = system.find("e:TimeCreated", _NS)
            message = event.find("e:RenderingInfo/e:Message", _NS)
            rows.append(
                {
                    "id": f"{log_name}-{system.findtext('e:EventRecordID', '', _NS)}",
                    "time": created.get("SystemTime") if created is not None else None,
                    "log": log_name,
                    "level": _LEVELS.get(system.findtext("e:Level", "", _NS), ""),
                    "source": provider.get("Name") if provider is not None else "",
                    "event": system.findtext("e:EventID", "", _NS),
                    "message": " ".join((message.text or "").split())[:400]
                    if message is not None
                    else "",
                }
            )
    rows.sort(key=lambda r: r["time"] or "", reverse=True)
    sources: dict[str, int] = {}
    for row in rows:
        source = str(row["source"] or "")
        sources[source] = sources.get(source, 0) + 1
    top = sorted(sources.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return ToolResult(
        summary=[
            fact("Eventos", len(rows), Tone.WARN if rows else Tone.OK),
            fact("Orígenes más frecuentes", ", ".join(f"{k} ({v})" for k, v in top) or None),
        ],
        tables=[
            table(
                "eventos",
                f"Errores de las últimas {hours} h",
                [
                    col("time", "Fecha", ColumnKind.DATE),
                    col("level", "Nivel"),
                    col("source", "Origen"),
                    col("event", "Id", priority=2),
                    col("log", "Registro", priority=3),
                    col("message", "Mensaje", priority=2),
                ],
                rows,
                "id",
            )
        ],
    )


events = SupportTool(
    tool(
        "system.events",
        "Sistema",
        "Errores recientes del sistema",
        "Errores y eventos críticos de los registros Sistema y Aplicación.",
        Risk.READ,
        params=[
            number("hours", "Últimas horas", default=24),
            flag("warnings", "Incluir advertencias"),
        ],
    ),
    lambda p, _e: [
        step(
            "Leer eventos",
            'wevtutil qe System /q:"*[System[(Level=1 or Level=2)]]" /c:200 /rd:true',
        )
    ],
    _events,
)


# --- Reparación ------------------------------------------------------------------------------------


def _sfc(_params: Params, ctx: ToolContext) -> ToolResult:
    output = ctx.command([SFC, "/scannow"], timeout_s=3600)
    lines = [line.strip() for line in output.stdout.splitlines() if line.strip()]
    summary = " ".join(lines[-3:])
    return ToolResult(
        summary=[fact("Resultado", summary)],
        checks=[
            check(
                "Comprobación de archivos del sistema",
                output.ok,
                "Detalle en %WinDir%\\Logs\\CBS\\CBS.log",
            )
        ],
        verified=output.ok,
    )


sfc = SupportTool(
    tool(
        "system.sfc",
        "Sistema",
        "Reparar archivos del sistema (SFC)",
        "Comprueba y repara archivos protegidos de Windows. Tarda entre 5 y 20 minutos.",
        Risk.CHANGE,
        admin=True,
        hidden=True,
    ),
    lambda _p, _e: [step("Comprobar y reparar", "sfc /scannow")],
    _sfc,
)


def _dism(_params: Params, ctx: ToolContext) -> ToolResult:
    check_health = ctx.command([DISM, "/Online", "/Cleanup-Image", "/ScanHealth"], timeout_s=3600)
    restore = ctx.command([DISM, "/Online", "/Cleanup-Image", "/RestoreHealth"], timeout_s=7200)
    return ToolResult(
        checks=[
            check("Análisis de la imagen", check_health.ok),
            check(
                "Restauración de la imagen",
                restore.ok,
                None
                if restore.ok
                else "Sin Internet o WSUS, DISM no puede descargar los archivos de reparación",
            ),
        ],
        verified=restore.ok,
    )


dism = SupportTool(
    tool(
        "system.dism",
        "Sistema",
        "Reparar la imagen de Windows (DISM)",
        "Analiza y repara el almacén de componentes; descarga lo que falte desde Windows Update.",
        Risk.CHANGE,
        admin=True,
        network=True,
        hidden=True,
    ),
    lambda _p, _e: [
        step("Analizar", "Dism /Online /Cleanup-Image /ScanHealth"),
        step("Reparar", "Dism /Online /Cleanup-Image /RestoreHealth"),
        step("Después conviene ejecutar SFC"),
    ],
    _dism,
)


def _restore_point(params: Params, ctx: ToolContext) -> ToolResult:
    description = params["description"]

    def by_wmi() -> bool:
        try:
            result = call_method(
                "root/default",
                "SystemRestore",
                "CreateRestorePoint",
                {"Description": description, "RestorePointType": 12, "EventType": 100},
            )
        except (ComError, ValueError):
            return False
        return result.get("ReturnValue") == 0

    way = first_that_works(
        ctx,
        [
            Attempt("WMI SystemRestore.CreateRestorePoint", by_wmi),
            Attempt(
                "PowerShell Checkpoint-Computer",
                lambda: (
                    powershell(
                        ctx,
                        "Checkpoint-Computer -Description ([Console]::In.ReadToEnd().Trim()) -RestorePointType MODIFY_SETTINGS",
                        stdin=description,
                        timeout_s=600,
                    ).ok
                ),
            ),
        ],
    )
    return ToolResult(
        checks=[
            check(
                "Punto de restauración",
                way is not None,
                None if way else "Active Protección del sistema en la unidad C:",
            )
        ],
        verified=way is not None,
    )


restore_point = SupportTool(
    tool(
        "system.restore_point",
        "Sistema",
        "Crear punto de restauración",
        "Crea un punto de restauración antes de cambios importantes.",
        Risk.CHANGE,
        admin=True,
        params=[text("description", "Descripción", required=True, default="Honey Check")],
    ),
    lambda p, _e: [step("Crear punto", f'Checkpoint-Computer -Description "{p["description"]}"')],
    _restore_point,
    warnings=lambda _p, _e: [
        "Windows crea como máximo uno cada 24 horas: si ya hay uno reciente, no se crea otro."
    ],
)


def _wu_reset(_params: Params, ctx: ToolContext) -> ToolResult:
    windows = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows")
    services_list = ["wuauserv", "bits", "cryptsvc", "msiserver"]
    stopped = [s for s in services_list if stop_service(ctx, s)]
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    renamed = []
    try:
        for folder in (windows / "SoftwareDistribution", windows / "System32" / "catroot2"):
            if folder.exists():
                target = folder.with_name(f"{folder.name}.old-{stamp}")
                try:
                    folder.rename(target)
                    renamed.append(str(target))
                except OSError as error:
                    ctx.error(f"No se pudo renombrar {folder}: {error.strerror}")
    finally:
        started = [s for s in stopped if start_service(ctx, s)]
    return ToolResult(
        summary=[fact("Carpetas renombradas (se pueden borrar luego)", ", ".join(renamed) or None)],
        checks=[
            check("Servicios detenidos", len(stopped) == len(services_list)),
            check("Caché de Windows Update renovada", len(renamed) == 2),
            check("Servicios iniciados de nuevo", len(started) == len(stopped)),
        ],
        verified=len(renamed) == 2 and len(started) == len(stopped),
    )


wu_reset = SupportTool(
    tool(
        "system.windows_update_reset",
        "Sistema",
        "Restablecer Windows Update",
        "Detiene los servicios, renueva las cachés SoftwareDistribution y catroot2 y vuelve a iniciarlos.",
        Risk.CHANGE,
        admin=True,
        hidden=True,
    ),
    lambda _p, _e: [
        step(
            "Detener servicios",
            "net stop wuauserv & net stop bits & net stop cryptsvc & net stop msiserver",
        ),
        step(
            "Renombrar cachés",
            "ren %WinDir%\\SoftwareDistribution SoftwareDistribution.old & ren %WinDir%\\System32\\catroot2 catroot2.old",
        ),
        step(
            "Iniciar servicios",
            "net start wuauserv & net start bits & net start cryptsvc & net start msiserver",
        ),
    ],
    _wu_reset,
    warnings=lambda _p, _e: [
        "Se pierde el historial de actualizaciones mostrado en Configuración (las actualizaciones instaladas siguen instaladas)."
    ],
)


# --- Reinicio y batería -----------------------------------------------------------------------------


def _reboot(params: Params, ctx: ToolContext) -> ToolResult:
    seconds = max(30, int(params["seconds"]))
    output = ctx.command(
        [
            SHUTDOWN,
            "/r",
            "/t",
            str(seconds),
            "/c",
            "Reinicio solicitado por soporte técnico (Honey Check)",
            "/d",
            "p:4:1",
        ],
        timeout_s=30,
    )
    return ToolResult(
        checks=[check(f"Reinicio programado en {seconds} s", output.ok)],
        summary=[fact("Para cancelarlo", "Use «Cancelar reinicio»", Tone.WARN)],
        verified=output.ok,
    )


reboot = SupportTool(
    tool(
        "system.reboot",
        "Sistema",
        "Reiniciar el equipo",
        "Programa un reinicio con aviso al usuario; se puede cancelar antes de que ocurra.",
        Risk.DESTRUCTIVE,
        params=[number("seconds", "Segundos de aviso", default=120)],
    ),
    lambda p, _e: [step("Programar reinicio", f"shutdown /r /t {p['seconds']}")],
    _reboot,
    warnings=lambda _p, _e: [
        "Se cierra Honey Check y todo lo abierto; guarde el trabajo del usuario."
    ],
)


def _abort(_params: Params, ctx: ToolContext) -> ToolResult:
    output = ctx.command([SHUTDOWN, "/a"], timeout_s=30)
    return ToolResult(
        checks=[
            check(
                "Reinicio cancelado",
                output.ok,
                None if output.ok else "No había un reinicio programado",
            )
        ],
        verified=output.ok,
    )


abort = SupportTool(
    tool(
        "system.reboot_cancel",
        "Sistema",
        "Cancelar reinicio",
        "Cancela un reinicio o apagado programado.",
        Risk.CHANGE,
    ),
    lambda _p, _e: [step("Cancelar", "shutdown /a")],
    _abort,
)


def _battery(_params: Params, ctx: ToolContext) -> ToolResult:
    target = ctx.output_path("informe-bateria.html")
    output = ctx.command([POWERCFG, "/batteryreport", "/output", str(target)], timeout_s=120)
    ok = output.ok and target.is_file()
    return ToolResult(
        files=[FileRef(label="Informe de batería", path=str(target))] if ok else [],
        checks=[
            check(
                "Informe generado",
                ok,
                None if ok else "Este equipo no tiene batería o powercfg no está disponible",
            )
        ],
        verified=ok,
    )


battery = SupportTool(
    tool(
        "system.battery_report",
        "Sistema",
        "Informe de batería",
        "Genera el informe de Windows con capacidad, ciclos y uso de la batería.",
        Risk.READ,
    ),
    lambda _p, _e: [
        step("Generar informe", "powercfg /batteryreport /output informe-bateria.html")
    ],
    _battery,
)

TOOLS = [
    services,
    control,
    processes,
    kill,
    startup,
    toggle,
    events,
    sfc,
    dism,
    restore_point,
    wu_reset,
    reboot,
    abort,
    battery,
]
