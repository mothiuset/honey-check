"""Impresoras: consulta SNMP (modelo, serial, contador, consumibles), cola, servicio, página de prueba,
predeterminada, agregar por IP y quitar. Cada acción tiene vías alternativas y se verifica."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from honey_check.application.ports import CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import ToolContext
from honey_check.domain.support import Chart, ChartKind, ColumnKind, Risk, Tone, ToolResult
from honey_check.infrastructure.windows.com import ComError
from honey_check.infrastructure.windows.wmi import call_method

from ..base import (
    Params,
    SupportTool,
    check,
    col,
    fact,
    link,
    secret,
    step,
    table,
    text,
    tool,
)
from ..runner import tool_path
from ..snmp import SnmpClient, SnmpError, mac
from ..snmp import text as snmp_text
from ..winops import powershell, start_service, stop_service, wmi_rows

RUNDLL32 = tool_path("rundll32.exe")
CSCRIPT = tool_path("cscript.exe")
_IP = r"\d{1,3}(\.\d{1,3}){3}|[A-Za-z0-9.-]{1,253}"
_PRINTER = r"[^\"'\r\n\x00]{1,200}"

_OIDS = {
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "sysName": "1.3.6.1.2.1.1.5.0",
    "sysLocation": "1.3.6.1.2.1.1.6.0",
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "model": "1.3.6.1.2.1.25.3.2.1.3.1",
    "serial": "1.3.6.1.2.1.43.5.1.1.17.1",
    "pages": "1.3.6.1.2.1.43.10.2.1.4.1.1",
    "status": "1.3.6.1.2.1.25.3.5.1.1.1",
}
_SUPPLY_NAME = "1.3.6.1.2.1.43.11.1.1.6.1"
_SUPPLY_MAX = "1.3.6.1.2.1.43.11.1.1.8.1"
_SUPPLY_LEVEL = "1.3.6.1.2.1.43.11.1.1.9.1"
_IF_MAC = "1.3.6.1.2.1.2.2.1.6"
_STATUS = {1: "Otro", 2: "Desconocido", 3: "Lista", 4: "Imprimiendo", 5: "Calentando"}


def _snmp(params: Params, ctx: ToolContext) -> ToolResult:
    client = SnmpClient(params["host"], str(params.get("community") or "public"))
    try:
        values = client.get(list(_OIDS.values()))
    except SnmpError as error:
        raise ValueError(
            f"{error}. Compruebe la IP, que SNMP esté activo en la impresora y la comunidad."
        ) from error
    named = {key: values.get(oid) for key, oid in _OIDS.items()}
    ctx.info("La impresora respondió por SNMP")
    names = dict(client.walk(_SUPPLY_NAME))
    maxima = dict(client.walk(_SUPPLY_MAX))
    levels = dict(client.walk(_SUPPLY_LEVEL))
    supplies: list[dict[str, Any]] = []
    for oid, name in names.items():
        index = oid.rsplit(".", 1)[1]
        level = levels.get(f"{_SUPPLY_LEVEL}.{index}")
        maximum = maxima.get(f"{_SUPPLY_MAX}.{index}")
        percent = (
            round(100 * level / maximum)
            if isinstance(level, int) and isinstance(maximum, int) and maximum > 0 and level >= 0
            else None
        )
        state = (
            "Sin dato"
            if percent is None and level in (-2, -3, None)
            else ("Queda algo" if level == -3 else None)
        )
        supplies.append(
            {
                "name": snmp_text(name) or f"Consumible {index}",
                "percent": percent,
                "state": state or ("Bajo" if percent is not None and percent <= 15 else "Correcto"),
            }
        )
    address = next((m for _, v in client.walk(_IF_MAC, 8) if (m := mac(v))), None)
    uptime = named["sysUpTime"]
    low = [s["name"] for s in supplies if s["percent"] is not None and s["percent"] <= 15]
    return ToolResult(
        summary=[
            fact("Modelo", snmp_text(named["model"]) or snmp_text(named["sysDescr"])),
            fact("Número de serie", snmp_text(named["serial"])),
            fact("Nombre en la red", snmp_text(named["sysName"])),
            fact("Ubicación", snmp_text(named["sysLocation"])),
            fact("MAC", address),
            fact("Páginas impresas", named["pages"]),
            fact(
                "Estado", _STATUS.get(named["status"]) if isinstance(named["status"], int) else None
            ),
            fact(
                "Encendida hace",
                f"{int(uptime / 8_640_000)} días" if isinstance(uptime, int) else None,
            ),
            fact("Consumibles bajos", ", ".join(low) or "Ninguno", Tone.WARN if low else Tone.OK),
        ],
        charts=[
            Chart(
                id="consumibles",
                title="Nivel de consumibles (%)",
                kind=ChartKind.BAR,
                unit="percent",
                data=[
                    {"name": s["name"], "value": s["percent"]}
                    for s in supplies
                    if s["percent"] is not None
                ],
            )
        ],
        tables=[
            table(
                "consumibles",
                "Consumibles",
                [
                    col("name", "Consumible"),
                    col("percent", "Nivel %", ColumnKind.NUMBER),
                    col("state", "Estado"),
                ],
                supplies,
                "name",
            )
        ],
    )


snmp_query = SupportTool(
    tool(
        "printers.snmp",
        "Impresoras",
        "Consultar impresora de red (SNMP)",
        "Lee de la impresora su modelo, serial, contador de páginas, MAC y el nivel de tóner y demás consumibles.",
        Risk.READ,
        params=[
            text("host", "IP de la impresora", required=True, pattern=_IP),
            secret("community", "Comunidad SNMP", help="Si se deja vacío se usa public"),
        ],
        network=True,
    ),
    lambda p, _e: [
        step(
            f"Consulta SNMP v2c a {p['host']} (UDP 161)",
            f"snmpget -v2c -c public {p['host']} 1.3.6.1.2.1.43.5.1.1.17.1",
        )
    ],
    _snmp,
)


def _jobs() -> int | None:
    try:
        return len(wmi_rows(CimQuery("root/cimv2", "Win32_PrintJob", ("Name",))))
    except OSError:
        return None


def _spool_folder() -> Path:
    return Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "spool" / "PRINTERS"


def _clear_queue(_params: Params, ctx: ToolContext) -> ToolResult:
    before = _jobs()
    stopped = stop_service(ctx, "Spooler")
    removed = 0
    try:
        for path in _spool_folder().glob("*"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                ctx.warn(f"No se pudo borrar {path.name}")
    finally:
        started = start_service(ctx, "Spooler")
    after = _jobs()
    return ToolResult(
        summary=[
            fact("Trabajos antes", before),
            fact("Trabajos ahora", after),
            fact("Archivos de cola borrados", removed),
        ],
        checks=[
            check("Servicio de impresión detenido", stopped),
            check("Servicio de impresión en marcha", started),
            check("Cola vacía", after == 0 if after is not None else None),
        ],
        verified=started and (after == 0 if after is not None else True),
    )


clear_queue = SupportTool(
    tool(
        "printers.clear_queue",
        "Impresoras",
        "Vaciar la cola de impresión",
        "Detiene el servicio de impresión, borra los trabajos atascados y lo vuelve a iniciar.",
        Risk.CHANGE,
        admin=True,
        hidden=True,
    ),
    lambda _p, _e: [
        step("Detener el servicio de impresión", "net stop spooler"),
        step("Borrar trabajos atascados", 'del /q "%SystemRoot%\\System32\\spool\\PRINTERS\\*"'),
        step("Iniciar el servicio de impresión", "net start spooler"),
    ],
    _clear_queue,
    warnings=lambda _p, _e: ["Se pierden todos los trabajos pendientes de todas las impresoras."],
)


def _restart_spooler(_params: Params, ctx: ToolContext) -> ToolResult:
    stopped = stop_service(ctx, "Spooler")
    started = start_service(ctx, "Spooler")
    return ToolResult(
        checks=[check("Detenido", stopped), check("En marcha", started)], verified=started
    )


restart_spooler = SupportTool(
    tool(
        "printers.restart_spooler",
        "Impresoras",
        "Reiniciar el servicio de impresión",
        "Reinicia el servicio Spooler sin borrar trabajos.",
        Risk.CHANGE,
        admin=True,
        hidden=True,
    ),
    lambda _p, _e: [step("Detener", "net stop spooler"), step("Iniciar", "net start spooler")],
    _restart_spooler,
)


def _wmi_printer(name: str, method_name: str) -> bool:
    if '"' in name or "\\" in name:
        return False
    try:
        result = call_method("root/cimv2", f'Win32_Printer.DeviceID="{name}"', method_name)
    except (ComError, ValueError):
        return False
    return result.get("ReturnValue") == 0


def _test_page(params: Params, ctx: ToolContext) -> ToolResult:
    name = params["printer"]
    way = first_that_works(
        ctx,
        [
            Attempt("WMI Win32_Printer.PrintTestPage", lambda: _wmi_printer(name, "PrintTestPage")),
            Attempt(
                "printui /k",
                lambda: (
                    ctx.command(
                        [RUNDLL32, "printui.dll,PrintUIEntry", "/k", "/n", name], timeout_s=60
                    ).ok
                ),
            ),
        ],
    )
    return ToolResult(
        checks=[check("Página de prueba enviada", way is not None, "Revise la impresora")],
        verified=way is not None,
    )


_NAME = [
    text(
        "printer",
        "Impresora",
        required=True,
        pattern=_PRINTER,
        help="Nombre como aparece en Windows",
    )
]

test_page = SupportTool(
    tool(
        "printers.test_page",
        "Impresoras",
        "Imprimir página de prueba",
        "Envía la página de prueba de Windows a una impresora.",
        Risk.CHANGE,
        params=_NAME,
        hidden=True,
        instant=True,
    ),
    lambda p, _e: [
        step("Página de prueba", f'rundll32 printui.dll,PrintUIEntry /k /n "{p["printer"]}"')
    ],
    _test_page,
)


def _is_default(name: str) -> bool:
    try:
        rows = wmi_rows(CimQuery("root/cimv2", "Win32_Printer", ("Name", "Default")))
    except OSError:
        return False
    return any(r.get("Name") == name and r.get("Default") for r in rows)


def _set_default(params: Params, ctx: ToolContext) -> ToolResult:
    name = params["printer"]
    first_that_works(
        ctx,
        [
            Attempt(
                "WMI Win32_Printer.SetDefaultPrinter",
                lambda: _wmi_printer(name, "SetDefaultPrinter") and _is_default(name),
            ),
            Attempt(
                "printui /y",
                lambda: (
                    ctx.command(
                        [RUNDLL32, "printui.dll,PrintUIEntry", "/y", "/n", name], timeout_s=60
                    ).ok
                    and _is_default(name)
                ),
            ),
        ],
    )
    ok = _is_default(name)
    return ToolResult(
        checks=[
            check(
                "Es la predeterminada",
                ok,
                None
                if ok
                else "Si Windows administra la predeterminada, desactívelo en Configuración > Impresoras",
            )
        ],
        verified=ok,
    )


set_default = SupportTool(
    tool(
        "printers.set_default",
        "Impresoras",
        "Usar como predeterminada",
        "Marca la impresora como predeterminada para el usuario actual.",
        Risk.CHANGE,
        params=_NAME,
        hidden=True,
    ),
    lambda p, _e: [
        step("Predeterminada", f'rundll32 printui.dll,PrintUIEntry /y /n "{p["printer"]}"')
    ],
    _set_default,
)


def _admin_script(name: str) -> Path | None:
    base = (
        Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "Printing_Admin_Scripts"
    )
    return next(iter(sorted(base.glob(f"*/{name}"))), None)


def _printer_exists(name: str) -> bool:
    try:
        return any(
            r.get("Name") == name
            for r in wmi_rows(CimQuery("root/cimv2", "Win32_Printer", ("Name",)))
        )
    except OSError:
        return False


def _remove(params: Params, ctx: ToolContext) -> ToolResult:
    name = params["printer"]
    first_that_works(
        ctx,
        [
            Attempt(
                "PowerShell Remove-Printer",
                lambda: (
                    powershell(
                        ctx, "Remove-Printer -Name ([Console]::In.ReadToEnd().Trim())", stdin=name
                    ).ok
                    and not _printer_exists(name)
                ),
            ),
            Attempt(
                "printui /dl",
                lambda: (
                    ctx.command(
                        [RUNDLL32, "printui.dll,PrintUIEntry", "/dl", "/n", name], timeout_s=60
                    ).ok
                    and not _printer_exists(name)
                ),
            ),
        ],
    )
    gone = not _printer_exists(name)
    return ToolResult(checks=[check(f"Impresora «{name}» quitada", gone)], verified=gone)


remove = SupportTool(
    tool(
        "printers.remove",
        "Impresoras",
        "Quitar impresora",
        "Quita la impresora de Windows (el driver y el puerto quedan instalados).",
        Risk.DESTRUCTIVE,
        params=_NAME,
        hidden=True,
    ),
    lambda p, _e: [
        step("Quitar la impresora", f'Remove-Printer -Name "{p["printer"]}"'),
        step("Si falla", f'rundll32 printui.dll,PrintUIEntry /dl /n "{p["printer"]}"'),
    ],
    _remove,
)


def _printers(_params: Params, _ctx: ToolContext) -> ToolResult:
    rows = wmi_rows(
        CimQuery(
            "root/cimv2",
            "Win32_Printer",
            ("Name", "PortName", "DriverName", "Default", "WorkOffline"),
        )
    )
    data = [
        {
            "name": r.get("Name"),
            "port": r.get("PortName"),
            "driver": r.get("DriverName"),
            "default": bool(r.get("Default")),
            "offline": bool(r.get("WorkOffline")),
        }
        for r in rows
    ]
    return ToolResult(
        tables=[
            table(
                "impresoras",
                "Impresoras",
                [
                    col("name", "Impresora"),
                    col("port", "Puerto"),
                    col("driver", "Driver", priority=2),
                    col("default", "Predeterminada", ColumnKind.BOOL),
                    col("offline", "Sin conexión", ColumnKind.BOOL, 2),
                ],
                data,
                "name",
                actions=[
                    link("printers.test_page", "Página de prueba", printer="{name}"),
                    link("printers.set_default", "Predeterminada", printer="{name}"),
                    link("printers.remove", "Quitar", Tone.BAD, printer="{name}"),
                ],
            )
        ]
    )


printers_list = SupportTool(
    tool(
        "printers.list",
        "Impresoras",
        "Impresoras instaladas",
        "Lista las impresoras con acciones: página de prueba, predeterminada y quitar.",
        Risk.READ,
    ),
    lambda _p, _e: [step("Listar impresoras", "Get-Printer")],
    _printers,
)

TOOLS = [
    printers_list,
    snmp_query,
    test_page,
    set_default,
    clear_queue,
    restart_spooler,
    remove,
]
