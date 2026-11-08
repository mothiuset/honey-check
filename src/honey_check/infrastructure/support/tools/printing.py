"""«La impresora no imprime»: diagnóstico de la impresora elegida y arreglo solo de la causa.

Orden: servicio de impresión → la impresora existe → marcada «sin conexión» → en pausa → errores
físicos que ella informa (papel, tóner, atasco, puerta) → responde en su puerto de red → trabajos
atascados. Se arregla lo que depende del equipo (iniciar el servicio, ponerla en línea,
reanudarla, quitar solo los trabajos atascados); lo físico o de red se explica con lo que hay que
revisar. Al final se vuelve a diagnosticar y, si se pidió, se imprime una página de prueba.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from honey_check.application.ports import CancelToken, CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import CommandOutput, SupportEnvironment, ToolContext
from honey_check.domain.support import Check, CheckStatus, Choice, Risk, ToolResult
from honey_check.infrastructure.windows.netdiag import tcp_port_open

from ..base import Params, SupportTool, fact, flag, link, source_choice, step, tool
from ..runner import tool_path
from ..winops import powershell, wmi_rows

SC = tool_path("sc.exe")
_PRINTER = r"[^\"'\r\n\x00]{1,200}"
_STUCK_AFTER = timedelta(minutes=5)
# DetectedErrorState de Win32_Printer: lo que la impresora informa de sí misma.
_PHYSICAL = {
    4: "No tiene papel",
    6: "No tiene tóner o tinta",
    7: "Tiene una puerta o tapa abierta",
    8: "Tiene papel atascado",
    10: "Pide servicio técnico",
    11: "La bandeja de salida está llena",
}
_LOW = {3: "Le queda poco papel", 5: "Le queda poco tóner o tinta"}
_PAUSED = 8  # ExtendedPrinterStatus
_VIRTUAL_PORTS = ("nul:", "portprompt:", "file:", "xps", "onenote")
_IN_PS = (
    "$n = [Console]::In.ReadToEnd().Trim(); $p = Get-CimInstance Win32_Printer | ? Name -eq $n;"
)

# --- Lo que se lee del equipo (funciones de módulo: las pruebas las simulan) -------------------


def _number(value: object, default: int = 0) -> int:
    return int(value) if isinstance(value, int | float) else default


@dataclass(frozen=True)
class Printer:
    name: str
    port: str
    driver: str
    offline: bool
    error_state: int
    extended_status: int
    default: bool
    network: bool


@dataclass(frozen=True)
class Job:
    id: int
    document: str
    status: str
    submitted: datetime | None


def printers() -> list[Printer]:
    rows = wmi_rows(
        CimQuery(
            "root/cimv2",
            "Win32_Printer",
            (
                "Name",
                "PortName",
                "DriverName",
                "WorkOffline",
                "DetectedErrorState",
                "ExtendedPrinterStatus",
                "Default",
                "Network",
            ),
        )
    )
    return [
        Printer(
            name=str(r.get("Name") or ""),
            port=str(r.get("PortName") or ""),
            driver=str(r.get("DriverName") or ""),
            offline=bool(r.get("WorkOffline")),
            error_state=_number(r.get("DetectedErrorState"), 0),
            extended_status=_number(r.get("ExtendedPrinterStatus"), 0),
            default=bool(r.get("Default")),
            network=bool(r.get("Network")),
        )
        for r in rows
    ]


def port_address(port: str) -> tuple[str, int] | None:
    """Dirección y puerto TCP de un puerto de impresora (TCP/IP estándar o «IP_x.x.x.x»)."""
    rows = wmi_rows(
        CimQuery("root/cimv2", "Win32_TCPIPPrinterPort", ("Name", "HostAddress", "PortNumber"))
    )
    for row in rows:
        if str(row.get("Name")).lower() == port.lower() and row.get("HostAddress"):
            return str(row["HostAddress"]), _number(row.get("PortNumber"), 9100)
    match = re.match(r"^IP_(\d{1,3}(?:\.\d{1,3}){3})", port)
    return (match.group(1), 9100) if match else None


def jobs(printer: str) -> list[Job]:
    rows = wmi_rows(
        CimQuery(
            "root/cimv2", "Win32_PrintJob", ("Name", "JobId", "Document", "Status", "TimeSubmitted")
        )
    )
    found = []
    for row in rows:
        owner, _, _ = str(row.get("Name") or "").rpartition(",")
        if owner.strip() != printer:
            continue
        submitted = row.get("TimeSubmitted")
        found.append(
            Job(
                id=_number(row.get("JobId"), 0),
                document=str(row.get("Document") or ""),
                status=str(row.get("Status") or ""),
                submitted=submitted if isinstance(submitted, datetime) else None,
            )
        )
    return found


def port_reachable(address: tuple[str, int]) -> bool:
    return tcp_port_open(address[0], address[1], 2.0)


def _run(env: SupportEnvironment, args: list[str], timeout_s: float = 20) -> CommandOutput:
    return env.runner.run(args, timeout_s=timeout_s, cancel=CancelToken())


def spooler_running(env: SupportEnvironment) -> bool:
    output = _run(env, [SC, "query", "Spooler"])
    return output.ok and ("RUNNING" in output.stdout or ": 4 " in output.stdout)


# --- Opciones: las impresoras del equipo ---------------------------------------------------------


def _is_virtual(printer: Printer) -> bool:
    port = printer.port.lower()
    return any(port.startswith(v) for v in _VIRTUAL_PORTS) or "pdf" in printer.driver.lower()


def printer_choices() -> list[Choice]:
    order = {"Predeterminada": 0, "De red": 1, "Locales": 2, "Virtuales (PDF, OneNote…)": 3}
    choices = []
    for printer in printers():
        group = (
            "Predeterminada"
            if printer.default
            else "Virtuales (PDF, OneNote…)"
            if _is_virtual(printer)
            else "De red"
            if printer.network or printer.port.upper().startswith(("IP_", "WSD"))
            else "Locales"
        )
        status = "sin conexión" if printer.offline else "lista"
        choices.append(
            Choice(
                value=printer.name,
                label=printer.name,
                group=group,
                detail=f"{printer.port}, {status}",
            )
        )
    return sorted(choices, key=lambda c: (order.get(c.group or "", 9), c.label.lower()))


SOURCES = {"printers": printer_choices}


# --- Diagnóstico --------------------------------------------------------------------------------


@dataclass
class Finding:
    key: str
    label: str
    status: CheckStatus
    detail: str
    fix: str | None = None

    def check(self) -> Check:
        return Check(label=self.label, status=self.status, detail=self.detail)


@dataclass
class Diagnosis:
    printer: Printer | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def fixes(self) -> list[str]:
        return [f.fix for f in self.findings if f.fix]

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.status is CheckStatus.FAIL and not f.fix]


def _jobs_phrase(count: int) -> str:
    return f"{count} trabajo trabado" if count == 1 else f"{count} trabajos trabados"


def _stuck(job: Job) -> bool:
    status = job.status.lower()
    if any(word in status for word in ("error", "paused", "pausa", "deleting", "eliminando")):
        return True
    return job.submitted is not None and datetime.now(UTC) - job.submitted > _STUCK_AFTER


def diagnose(env: SupportEnvironment, name: str) -> Diagnosis:
    found = Diagnosis()
    add = found.findings.append
    if not spooler_running(env):
        add(
            Finding(
                "spooler",
                "Servicio de impresión",
                CheckStatus.WARN,
                "Está detenido: nada se imprime. Se inicia.",
                fix="start_spooler",
            )
        )
        return found  # sin el servicio no se puede leer la impresora ni su cola
    add(Finding("spooler", "Servicio de impresión", CheckStatus.OK, "En ejecución"))

    printer = next((p for p in printers() if p.name == name), None)
    found.printer = printer
    if printer is None:
        add(
            Finding(
                "printer",
                name,
                CheckStatus.FAIL,
                "Ya no está instalada en este equipo. Agréguela de nuevo.",
            )
        )
        return found
    add(Finding("printer", "Impresora", CheckStatus.OK, f"{printer.driver}, puerto {printer.port}"))

    if printer.offline:
        add(
            Finding(
                "offline",
                "Marcada «sin conexión»",
                CheckStatus.WARN,
                "Windows la tiene en modo sin conexión y guarda los trabajos. Se pone en línea.",
                fix="online",
            )
        )
    if printer.extended_status == _PAUSED:
        add(
            Finding(
                "paused",
                "En pausa",
                CheckStatus.WARN,
                "La impresión está en pausa. Se reanuda.",
                fix="resume",
            )
        )
    if printer.error_state in _PHYSICAL:
        add(
            Finding(
                "physical",
                _PHYSICAL[printer.error_state],
                CheckStatus.FAIL,
                "Lo informa la propia impresora: hay que resolverlo en el equipo físico.",
            )
        )
    elif printer.error_state in _LOW:
        add(Finding("physical", _LOW[printer.error_state], CheckStatus.INFO, "Todavía imprime"))

    address = port_address(printer.port) if not _is_virtual(printer) else None
    if address:
        if port_reachable(address):
            add(
                Finding(
                    "port",
                    "Conexión de red",
                    CheckStatus.OK,
                    f"Responde en {address[0]}:{address[1]}",
                )
            )
        else:
            add(
                Finding(
                    "port",
                    "Conexión de red",
                    CheckStatus.FAIL,
                    f"No responde en {address[0]}:{address[1]}: está apagada, desconectada o "
                    "cambió de dirección IP. Revise la impresora o su IP.",
                )
            )

    stuck = [job for job in jobs(printer.name) if _stuck(job)]
    if stuck:
        add(
            Finding(
                "queue",
                "Trabajos atascados",
                CheckStatus.WARN,
                f"{_jobs_phrase(len(stuck)).capitalize()} "
                f"{'bloquea' if len(stuck) == 1 else 'bloquean'} la cola (por ejemplo "
                f"«{stuck[0].document}»). Se quitan solo esos.",
                fix="clear_jobs",
            )
        )
    else:
        add(Finding("queue", "Cola", CheckStatus.OK, "Sin trabajos trabados"))
    return found


# --- Revisión y ejecución ----------------------------------------------------------------------


_VERBS = {
    "start_spooler": "iniciar el servicio de impresión",
    "online": "ponerla en línea",
    "resume": "reanudarla",
    "clear_jobs": "quitar los trabajos atascados",
}


def _review(params: Params, env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    found = diagnose(env, params["printer"])
    checks = [f.check() for f in found.findings]
    if found.blocking and not found.fixes:
        return f"{found.blocking[0].label}: {found.blocking[0].detail}", checks, False
    if found.fixes:
        verbs = [_VERBS[f] for f in found.fixes]
        what = verbs[0] if len(verbs) == 1 else f"{', '.join(verbs[:-1])} y {verbs[-1]}"
        tail = " Lo demás hay que resolverlo en la impresora (ver abajo)." if found.blocking else ""
        return f"Se va a {what}. Después se comprueba de nuevo.{tail}", checks, True
    return "No se encontró un problema en el equipo ni en la impresora.", checks, False


def _fix(key: str, name: str, ctx: ToolContext) -> Check:
    def ps(script: str) -> bool:
        return powershell(ctx, f"{_IN_PS} {script}", stdin=name, timeout_s=60).ok

    if key == "start_spooler":

        def started() -> bool:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if spooler_running(ctx.env):
                    return True
                _pause(1)
            return False

        way = first_that_works(
            ctx,
            [
                Attempt(
                    "sc start Spooler",
                    lambda: (
                        ctx.command([SC, "start", "Spooler"], timeout_s=30).exit_code in (0, 1056)
                        and started()
                    ),
                ),
                Attempt(
                    "Start-Service Spooler",
                    lambda: (
                        powershell(ctx, "Start-Service Spooler -ErrorAction Stop").ok and started()
                    ),
                ),
            ],
        )
        label = "Iniciar el servicio de impresión"
    elif key == "online":
        way = first_that_works(
            ctx,
            [
                Attempt(
                    "Win32_Printer.WorkOffline",
                    lambda: ps(
                        "Set-CimInstance -InputObject $p -Property @{WorkOffline=$false} -ErrorAction Stop"
                    ),
                )
            ],
        )
        label = "Poner en línea"
    elif key == "resume":
        way = first_that_works(
            ctx,
            [
                Attempt(
                    "Win32_Printer.Resume",
                    lambda: ps(
                        "if ((Invoke-CimMethod -InputObject $p -MethodName Resume).ReturnValue -ne 0) { exit 1 }"
                    ),
                ),
            ],
        )
        label = "Reanudar"
    else:  # clear_jobs
        before = [job for job in jobs(name) if _stuck(job)]
        ids = ",".join(str(job.id) for job in before)
        way = first_that_works(
            ctx,
            [
                Attempt(
                    "Remove-PrintJob (solo los trabados)",
                    lambda: (
                        powershell(
                            ctx,
                            "$n, $ids = ([Console]::In.ReadToEnd().Trim() -split '\\|', 2); "
                            "foreach ($i in ($ids -split ',')) { Remove-PrintJob -PrinterName $n -ID ([int]$i) -ErrorAction Stop }",
                            stdin=f"{name}|{ids}",
                            timeout_s=60,
                        ).ok
                        and not [job for job in jobs(name) if _stuck(job)]
                    ),
                ),
            ],
        )
        label = f"Quitar {_jobs_phrase(len(before))}"
        if way is None:
            return Check(
                label=label,
                status=CheckStatus.FAIL,
                detail="Windows no los quitó. «Vaciar la cola de impresión» los borra todos, de "
                "todas las impresoras.",
                fix=link("printers.clear_queue", "Vaciar la cola"),
            )
    return Check(
        label=label,
        status=CheckStatus.OK if way else CheckStatus.FAIL,
        detail=f"Hecho ({way})" if way else "Windows no lo permitió por ninguna vía",
    )


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def _printing(params: Params, ctx: ToolContext) -> ToolResult:
    name = params["printer"]
    found = diagnose(ctx.env, name)
    applied: list[Check] = []
    tried: set[str] = set()
    # Iniciar el servicio puede destapar lo que sigue (la impresora en pausa): hasta dos rondas,
    # sin repetir un arreglo que ya se intentó.
    for _round in range(2):
        pending = [key for key in found.fixes if key not in tried]
        if not pending:
            break
        for key in pending:
            tried.add(key)
            ctx.info(f"Corrigiendo: {_VERBS[key]}")
            applied.append(_fix(key, name, ctx))
        found = diagnose(ctx.env, name)
    checks = [*applied, *[f.check() for f in found.findings]]
    if params.get("test_page") and found.printer and not found.blocking and not found.fixes:
        printed = powershell(
            ctx,
            f"{_IN_PS} if ((Invoke-CimMethod -InputObject $p -MethodName PrintTestPage).ReturnValue -ne 0) {{ exit 1 }}",
            stdin=name,
            timeout_s=60,
        ).ok
        checks.append(
            Check(
                label="Página de prueba",
                status=CheckStatus.OK if printed else CheckStatus.FAIL,
                detail="Enviada: compruebe que salió en papel"
                if printed
                else "Windows no la envió",
            )
        )
    ok = not found.fixes and not found.blocking
    return ToolResult(
        summary=[
            fact("Impresora", name),
            fact("Estado", "Lista para imprimir" if ok else "Sigue con problemas"),
        ],
        checks=checks,
        verified=ok,
    )


printing = SupportTool(
    tool(
        "printers.fix",
        "Impresoras",
        "La impresora no imprime",
        "Revisa el servicio de impresión, la impresora (sin conexión, en pausa, papel, tóner, "
        "atascos), su conexión de red y los trabajos trabados; corrige lo que depende del equipo "
        "y comprueba.",
        Risk.CHANGE,
        admin=True,
        params=[
            source_choice("printer", "Impresora", "printers", pattern=_PRINTER),
            flag("test_page", "Imprimir una página de prueba al terminar", default=True),
        ],
        network=True,
        action="Corregir la impresora",
    ),
    lambda p, _e: [
        step("Servicio de impresión en ejecución", "sc query Spooler"),
        step("Estado de la impresora", f'Get-Printer -Name "{p["printer"]}"'),
        step("Conexión de red al puerto", "Test-NetConnection <IP> -Port 9100"),
        step("Trabajos trabados", f'Get-PrintJob -PrinterName "{p["printer"]}"'),
        step("Corregir solo lo encontrado y comprobar"),
    ],
    _printing,
    review=_review,
)

TOOLS = [printing]
