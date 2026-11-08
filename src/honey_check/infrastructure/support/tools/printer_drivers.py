"""Agregar una impresora de red sabiendo solo su IP, y los controladores de impresora.

La revisión pregunta a la impresora su modelo por SNMP y elige el controlador sola, en este orden:
el que eligió el técnico; uno de la carpeta que eligió; uno instalado cuyo nombre corresponde al
modelo; uno del almacén de controladores de Windows que declare ese modelo; el universal de la
marca; el genérico de Windows (PCL6). Dice cuál y de dónde sale antes de hacer nada.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from honey_check.application.ports import CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.drivers import (
    GENERIC_DRIVERS,
    UNIVERSAL_DRIVERS,
    best_printer_driver,
    decode_inf,
    parse_inf,
    printer_brand,
)
from honey_check.domain.support import Check, Choice, Risk, Tone, ToolResult

from ..base import (
    Params,
    SupportTool,
    check,
    col,
    fact,
    flag,
    link,
    number,
    source_choice,
    step,
    table,
    text,
    tool,
)
from ..runner import tool_path
from ..snmp import SnmpClient, SnmpError
from ..snmp import text as snmp_text
from ..winops import powershell, wmi_rows
from .drivers import installed_packages
from .printers import CSCRIPT, _admin_script, _printer_exists, _wmi_printer
from .printing import port_reachable

_CATEGORY = "Impresoras"
_PNPUTIL = tool_path("pnputil.exe")
_IP = r"\d{1,3}(\.\d{1,3}){3}|[A-Za-z0-9.-]{1,253}"
_NAME = r"[^\"'\r\n\x00]{1,200}"
_PATH = r"[^\"'\r\n\x00*?<>|]{3,400}"
_MODEL = "1.3.6.1.2.1.25.3.2.1.3.1"  # hrDeviceDescr: «HP LaserJet Pro M404dn»
_DESCR = "1.3.6.1.2.1.1.1.0"
_SYSNAME = "1.3.6.1.2.1.1.5.0"
_SERIAL = "1.3.6.1.2.1.43.5.1.1.17.1"


# --- Lo que hay en el equipo y en la red (la simulación reemplaza estas funciones) -------------------


def identify(host: str) -> dict[str, str]:
    """Modelo, nombre y serie que la impresora dice de sí misma por SNMP; vacío si no responde."""
    try:
        values = SnmpClient(host, "public", timeout_s=1.5, retries=0).get(
            [_MODEL, _DESCR, _SYSNAME, _SERIAL]
        )
    except (SnmpError, OSError):
        return {}
    found = {
        "model": snmp_text(values.get(_MODEL)) or snmp_text(values.get(_DESCR)),
        "name": snmp_text(values.get(_SYSNAME)),
        "serial": snmp_text(values.get(_SERIAL)),
    }
    return {key: value for key, value in found.items() if value}


def installed_driver_names() -> list[str]:
    rows = wmi_rows(CimQuery("root/StandardCimv2", "MSFT_PrinterDriver", ("Name",)))
    return sorted({str(row.get("Name")) for row in rows if row.get("Name")})


def printers_using(driver: str) -> list[str]:
    rows = wmi_rows(CimQuery("root/cimv2", "Win32_Printer", ("Name", "DriverName")))
    return [str(r.get("Name")) for r in rows if str(r.get("DriverName") or "") == driver]


_PRINTER_CLASS = re.compile(r"^\s*Class\s*=\s*Printer\s*$", re.IGNORECASE | re.MULTILINE)


def _printer_models(paths: list[Path]) -> dict[str, Path]:
    """Nombre de controlador → .inf, de los paquetes de clase Printer (los demás ni se leen
    enteros: la cabecera dice la clase)."""
    found: dict[str, Path] = {}
    for path in paths:
        try:
            text = decode_inf(path.read_bytes())
        except OSError:
            continue
        if not _PRINTER_CLASS.search(text[:4096]):
            continue
        driver = parse_inf(path.name, text)
        if (driver.driver_class or "").lower() == "printer":
            for model in driver.models:
                found.setdefault(model, path)
    return found


def store_models() -> dict[str, Path]:
    """Modelos que declaran los paquetes de impresora del almacén de controladores."""
    inf = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "INF"
    return _printer_models([inf / d.name for d in installed_packages()])


def folder_models(folder: Path) -> dict[str, Path]:
    paths = [folder] if folder.suffix.lower() == ".inf" else sorted(folder.rglob("*.inf"))[:2000]
    return _printer_models(paths)


# --- Qué controlador usar ------------------------------------------------------------------------

_ORIGIN = {
    "chosen": "el que eligió",
    "folder": "de la carpeta que eligió",
    "installed": "ya instalado",
    "store": "del almacén de controladores de Windows",
    "universal": "universal de la marca",
    "generic": "genérico de Windows",
}


@dataclass(frozen=True)
class DriverPlan:
    name: str
    origin: str
    inf: Path | None = None


def plan_driver(
    params: Params, model: str | None, store: dict[str, Path] | None = None
) -> DriverPlan | None:
    installed = installed_driver_names()
    if params.get("driver"):
        return DriverPlan(str(params["driver"]), "chosen")
    if params.get("driver_folder"):
        models = folder_models(Path(params["driver_folder"]))
        name = best_printer_driver(model, models) or (
            next(iter(models)) if len(models) == 1 else None
        )
        if name:
            return DriverPlan(name, "folder", models[name])
    if name := best_printer_driver(model, installed):
        return DriverPlan(name, "installed")
    store = store_models() if store is None else store
    if name := best_printer_driver(model, store):
        return DriverPlan(name, "store", store[name])
    for name in UNIVERSAL_DRIVERS.get(printer_brand(model) or "", ()):
        if name in installed:
            return DriverPlan(name, "universal")
    for name in GENERIC_DRIVERS:
        if name in installed:
            return DriverPlan(name, "generic")
    return None


def _printer_name(params: Params, identity: dict[str, str]) -> str:
    return str(params.get("name") or "").strip() or (
        f"{identity.get('model') or 'Impresora'} ({params['host']})"
    )


# --- Agregar por IP --------------------------------------------------------------------------------


def _add_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    host = params["host"]
    port = int(params.get("port") or 9100)
    # La impresora y su puerto se consultan a la vez: cada uno puede tardar si no responde.
    with ThreadPoolExecutor(max_workers=3) as pool:
        asked = pool.submit(identify, host)
        stored = pool.submit(store_models)
        reachable = pool.submit(port_reachable, (host, port)).result()
        identity = asked.result()
        store = stored.result()
    model = identity.get("model")
    name = _printer_name(params, identity)
    checks: list[Check] = []
    if model:
        serial = f", serie {identity['serial']}" if identity.get("serial") else ""
        checks.append(check(f"Impresora en {host}", True, f"Responde: {model}{serial}."))
    else:
        checks.append(
            check(
                f"Impresora en {host}",
                False,
                "No respondió por SNMP: no se sabe el modelo. Se usa el controlador elegido o el "
                "genérico; si imprime mal, elija la carpeta del controlador del fabricante.",
                warn=True,
            )
        )
    checks.append(
        check(
            f"Puerto {port}",
            reachable,
            "Abierto: la impresora recibe trabajos."
            if reachable
            else "No responde: revise la IP, que esté encendida y en la misma red.",
            warn=True,
        )
    )
    plan = plan_driver(params, model, store)
    if plan is None:
        checks.append(
            check(
                "Controlador",
                False,
                "No hay uno que sirva instalado ni en el almacén de Windows. Elija la carpeta del "
                "controlador del fabricante.",
            )
        )
    else:
        generic = plan.origin == "generic"
        checks.append(
            check(
                "Controlador",
                not generic,
                f"«{plan.name}», {_ORIGIN[plan.origin]}."
                + (
                    " Imprime en casi cualquier láser; si sale mal, elija la carpeta del fabricante."
                    if generic
                    else ""
                ),
                warn=generic,
            )
        )
    exists = _printer_exists(name)
    if exists:
        checks.append(check(f"«{name}»", False, "Ya existe una impresora con ese nombre."))
    summary = f"Se agregará «{name}» en {host}" + (
        f" con el controlador «{plan.name}»." if plan else ", pero falta el controlador."
    )
    return summary, checks, True


def _install_driver(plan: DriverPlan, ctx: ToolContext) -> bool:
    if plan.origin == "folder" and plan.inf:
        ctx.command([_PNPUTIL, "/add-driver", str(plan.inf), "/install"], timeout_s=300)
    if plan.origin in ("folder", "store"):
        powershell(
            ctx,
            "Add-PrinterDriver -Name ([Console]::In.ReadToEnd().Trim())",
            stdin=plan.name,
        )
    return plan.name in installed_driver_names()


def _add(params: Params, ctx: ToolContext) -> ToolResult:
    host = params["host"]
    identity = identify(host)
    name = _printer_name(params, identity)
    plan = plan_driver(params, identity.get("model"))
    if plan is None:
        raise ValueError("No hay controlador para esta impresora: elija la carpeta del fabricante")
    ctx.info(f"Controlador: {plan.name} ({_ORIGIN[plan.origin]})")
    if not _install_driver(plan, ctx):
        raise ValueError(f"No se pudo instalar el controlador «{plan.name}»")
    port_name, port = f"IP_{host}", int(params.get("port") or 9100)

    def by_powershell() -> bool:
        script = (
            "$d = [Console]::In.ReadToEnd() | ConvertFrom-Json;"
            "if (-not (Get-PrinterPort -Name $d.port -ErrorAction SilentlyContinue)) {"
            " Add-PrinterPort -Name $d.port -PrinterHostAddress $d.host -PortNumber $d.number };"
            "Add-Printer -Name $d.name -DriverName $d.driver -PortName $d.port"
        )
        payload = json.dumps(
            {"port": port_name, "host": host, "number": port, "name": name, "driver": plan.name}
        )
        return powershell(ctx, script, stdin=payload).ok and _printer_exists(name)

    def by_scripts() -> bool:
        prnport, prnmngr = _admin_script("prnport.vbs"), _admin_script("prnmngr.vbs")
        if prnport is None or prnmngr is None:
            return False
        ctx.command(
            [CSCRIPT, "//nologo", str(prnport), "-a", "-r", port_name, "-h", host, "-o", "raw",
             "-n", str(port)],
            timeout_s=120,
        )  # fmt: skip
        return ctx.command(
            [CSCRIPT, "//nologo", str(prnmngr), "-a", "-p", name, "-m", plan.name, "-r", port_name],
            timeout_s=120,
        ).ok and _printer_exists(name)

    way = first_that_works(
        ctx,
        [
            Attempt("PowerShell Add-PrinterPort/Add-Printer", by_powershell),
            Attempt("prnport.vbs y prnmngr.vbs", by_scripts),
        ],
    )
    checks = [
        check("Controlador", True, f"«{plan.name}», {_ORIGIN[plan.origin]}."),
        check(f"«{name}» instalada", way is not None, None if way else "Windows no la creó."),
    ]
    if way and params.get("test_page", True):
        printed = _wmi_printer(name, "PrintTestPage")
        checks.append(
            check(
                "Página de prueba",
                printed,
                "Enviada: revise la impresora." if printed else "No se pudo enviar.",
                warn=True,
            )
        )
    return ToolResult(
        summary=[fact("Impresora", name), fact("Modelo", identity.get("model"))],
        checks=checks,
        verified=way is not None,
    )


def driver_choices() -> list[Choice]:
    choices = [Choice(value="", label="Automático, según el modelo de la impresora")]
    for name in installed_driver_names():
        brand = printer_brand(name)
        group = (
            "Genéricos de Windows"
            if name in GENERIC_DRIVERS
            else (brand.capitalize() if brand else "Otros")
        )
        choices.append(Choice(value=name, label=name, group=group))
    return choices


SOURCES = {"printer_drivers": driver_choices}

add_network = SupportTool(
    tool(
        "printers.add_network",
        _CATEGORY,
        "Agregar impresora de red por IP",
        "Con solo la IP: pregunta a la impresora su modelo, elige el controlador y la agrega.",
        Risk.CHANGE,
        admin=True,
        params=[
            text("host", "IP de la impresora", required=True, pattern=_IP),
            text("name", "Nombre", pattern=_NAME, help="Opcional: si no, el modelo y la IP"),
            source_choice(
                "driver",
                "Controlador",
                "printer_drivers",
                pattern=r"|" + _NAME,
                help="Automático elige por el modelo; o uno ya instalado",
                required=False,
            ),
            text(
                "driver_folder",
                "Carpeta del controlador del fabricante",
                pattern=_PATH,
                help="Opcional: si el controlador no está en este equipo",
                browse="folder",
            ),
            number("port", "Puerto", default=9100),
            flag("test_page", "Imprimir una página de prueba al terminar", default=True),
        ],
        action="Agregar impresora",
    ),
    lambda p, _e: [
        step("Preguntar a la impresora su modelo", f"snmpget {p['host']} hrDeviceDescr"),
        step("Elegir e instalar el controlador", "Add-PrinterDriver -Name <controlador>"),
        step(
            "Crear el puerto y la impresora",
            f"Add-PrinterPort -Name IP_{p['host']} -PrinterHostAddress {p['host']}; Add-Printer",
        ),
    ],
    _add,
    review=_add_review,
)


# --- Controladores de impresora ------------------------------------------------------------------


def _drivers(_params: Params, _ctx: ToolContext) -> ToolResult:
    rows = wmi_rows(
        CimQuery(
            "root/StandardCimv2",
            "MSFT_PrinterDriver",
            ("Name", "Manufacturer", "PrinterEnvironment"),
        )
    )
    printers = wmi_rows(CimQuery("root/cimv2", "Win32_Printer", ("Name", "DriverName")))
    used: dict[str, list[str]] = {}
    for printer in printers:
        used.setdefault(str(printer.get("DriverName") or ""), []).append(str(printer.get("Name")))
    return ToolResult(
        checks=[
            check(
                "Agregar un controlador",
                None,
                "Si el de una impresora no está, instálelo desde la carpeta del fabricante.",
                link("printers.driver_add", "Agregar desde una carpeta"),
            )
        ],
        tables=[
            table(
                "drivers",
                "Controladores de impresora instalados",
                [
                    col("Name", "Controlador"),
                    col("Manufacturer", "Fabricante"),
                    col("printers", "Impresoras que lo usan"),
                    col("PrinterEnvironment", "Plataforma", priority=3),
                ],
                [
                    {
                        "Name": str(r.get("Name") or ""),
                        "Manufacturer": str(r.get("Manufacturer") or ""),
                        "PrinterEnvironment": str(r.get("PrinterEnvironment") or ""),
                        "printers": ", ".join(used.get(str(r.get("Name") or ""), [])) or "Ninguna",
                    }
                    for r in rows
                ],
                "Name",
                actions=[link("printers.driver_remove", "Quitar", Tone.BAD, driver="{Name}")],
            )
        ],
    )


drivers = SupportTool(
    tool(
        "printers.drivers",
        _CATEGORY,
        "Controladores de impresora",
        "Los instalados y qué impresoras los usan; agregar desde una carpeta o quitar.",
        Risk.READ,
    ),
    lambda _p, _e: [step("Listar controladores", "Get-PrinterDriver")],
    _drivers,
)


def _add_driver_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    folder = Path(params["folder"])
    if not folder.exists():
        return "No existe esa carpeta.", [check("Carpeta", False, str(folder))], False
    models = folder_models(folder)
    if not models:
        return (
            "La carpeta no tiene controladores de impresora (.inf de clase Printer).",
            [check("Carpeta", False, "Elija la carpeta donde se descomprimió el controlador.")],
            False,
        )
    packages = sorted({str(p) for p in models.values()})
    sample = ", ".join(sorted(models)[:4]) + ("…" if len(models) > 4 else "")
    return (
        f"Se agregarán {len(packages)} paquete{'s' if len(packages) != 1 else ''} con "
        f"{len(models)} modelos (por ejemplo {sample}). Después aparecen al agregar una impresora.",
        [check(Path(p).name, True) for p in packages],
        True,
    )


def _add_driver(params: Params, ctx: ToolContext) -> ToolResult:
    models = folder_models(Path(params["folder"]))
    packages = sorted({str(p) for p in models.values()})
    done = 0
    for package in packages:
        output = ctx.command([_PNPUTIL, "/add-driver", package, "/install"], timeout_s=300)
        done += output.exit_code in (0, 3010, 259)
    store = store_models()
    available = [m for m in models if m in store]
    return ToolResult(
        summary=[
            fact("Paquetes", f"{done} de {len(packages)}"),
            fact("Modelos disponibles", len(available)),
        ],
        checks=[
            check(
                "Controladores en Windows",
                bool(available),
                "Ya se pueden usar al agregar una impresora."
                if available
                else "Windows no los aceptó.",
            )
        ],
        verified=bool(available),
    )


driver_add = SupportTool(
    tool(
        "printers.driver_add",
        _CATEGORY,
        "Agregar controlador de impresora",
        "Instala en Windows los controladores de impresora de una carpeta del fabricante.",
        Risk.CHANGE,
        admin=True,
        params=[
            text("folder", "Carpeta del controlador", required=True, pattern=_PATH, browse="folder")
        ],
        action="Agregar",
    ),
    lambda p, _e: [
        step(
            "Agregar los paquetes al almacén",
            f'pnputil /add-driver "{p["folder"]}\\*.inf" /install',
        )
    ],
    _add_driver,
    review=_add_driver_review,
)


def _remove_driver_review(
    params: Params, _env: SupportEnvironment
) -> tuple[str, list[Check], bool]:
    name = params["driver"]
    users = printers_using(name)
    if users:
        return (
            f"«{name}» está en uso: quite antes esas impresoras o cámbieles el controlador.",
            [check(printer, False, "Usa este controlador.") for printer in users],
            False,
        )
    return f"Se quitará el controlador «{name}». Ninguna impresora lo usa.", [], True


def _remove_driver(params: Params, ctx: ToolContext) -> ToolResult:
    name = params["driver"]
    powershell(ctx, "Remove-PrinterDriver -Name ([Console]::In.ReadToEnd().Trim())", stdin=name)
    gone = name not in installed_driver_names()
    return ToolResult(checks=[check(f"«{name}» quitado", gone)], verified=gone)


driver_remove = SupportTool(
    tool(
        "printers.driver_remove",
        _CATEGORY,
        "Quitar controlador de impresora",
        "Quita un controlador de impresora que ninguna impresora usa.",
        Risk.DESTRUCTIVE,
        admin=True,
        hidden=True,
        params=[text("driver", "Controlador", required=True, pattern=_NAME)],
        action="Quitar",
    ),
    lambda p, _e: [step("Quitar el controlador", f'Remove-PrinterDriver -Name "{p["driver"]}"')],
    _remove_driver,
    review=_remove_driver_review,
)


def _change(params: Params, ctx: ToolContext) -> ToolResult:
    printer, driver = params["printer"], params["driver"]
    payload = json.dumps({"printer": printer, "driver": driver})
    powershell(
        ctx,
        "$d = [Console]::In.ReadToEnd() | ConvertFrom-Json; Set-Printer -Name $d.printer -DriverName $d.driver",
        stdin=payload,
    )
    rows = wmi_rows(CimQuery("root/cimv2", "Win32_Printer", ("Name", "DriverName")))
    ok = any(r.get("Name") == printer and r.get("DriverName") == driver for r in rows)
    return ToolResult(checks=[check(f"«{printer}» usa «{driver}»", ok)], verified=ok)


driver_change = SupportTool(
    tool(
        "printers.driver_change",
        _CATEGORY,
        "Cambiar el controlador de una impresora",
        "Para reparar una impresora que imprime mal: le pone otro controlador ya instalado.",
        Risk.CHANGE,
        admin=True,
        params=[
            source_choice("printer", "Impresora", "printers", pattern=_NAME),
            source_choice("driver", "Controlador", "printer_drivers", pattern=_NAME),
        ],
        action="Cambiar controlador",
    ),
    lambda p, _e: [
        step(
            "Cambiar el controlador",
            f'Set-Printer -Name "{p["printer"]}" -DriverName "{p["driver"]}"',
        )
    ],
    _change,
)

TOOLS = [add_network, drivers, driver_add, driver_remove, driver_change]
