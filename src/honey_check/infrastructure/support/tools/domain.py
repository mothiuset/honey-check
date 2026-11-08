"""Dominio y directivas: diagnóstico escalonado y correcciones (gpupdate resiliente, hora, Kerberos,
canal seguro).

El diagnóstico va de lo básico a lo específico: pertenencia, DNS, controlador, puertos, hora,
canal seguro, SYSVOL y última aplicación de directivas. Cada fallo ofrece su corrección.
"""

from __future__ import annotations

import os
import re
import socket
import winreg
from datetime import UTC, datetime, timedelta
from pathlib import Path

from honey_check.application.ports import CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import ToolContext
from honey_check.domain.support import Risk, Tone, ToolResult
from honey_check.infrastructure.windows.netdiag import (
    find_domain_controller,
    flush_dns_cache,
    remote_time_offset,
    tcp_port_open,
)

from ..base import Params, SupportTool, check, choice, fact, link, step, tool
from ..runner import tool_path
from ..winops import powershell, start_service, stop_service, wmi_rows

NLTEST = tool_path("nltest.exe")
GPUPDATE = tool_path("gpupdate.exe")
W32TM = tool_path("w32tm.exe")
KLIST = tool_path("klist.exe")
WEVTUTIL = tool_path("wevtutil.exe")
_PORTS = (
    (53, "DNS"),
    (88, "Kerberos"),
    (135, "RPC"),
    (389, "LDAP"),
    (445, "SMB (SYSVOL)"),
    (3268, "Catálogo global"),
)
_MACHINE_GPO = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine\Extension-List\{00000000-0000-0000-0000-000000000000}"
_MAX_SKEW_S = 300  # Kerberos rechaza diferencias de hora mayores a 5 minutos


def membership() -> tuple[bool, str | None]:
    try:
        rows = wmi_rows(CimQuery("root/cimv2", "Win32_ComputerSystem", ("PartOfDomain", "Domain")))
        if rows:
            return bool(rows[0].get("PartOfDomain")), str(rows[0].get("Domain") or "") or None
    except OSError:
        pass
    domain = os.environ.get("USERDNSDOMAIN")
    return bool(domain), domain


def last_machine_policy() -> datetime | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_GPO, 0, winreg.KEY_READ) as key:
            high, _ = winreg.QueryValueEx(key, "EndTimeHi")
            low, _ = winreg.QueryValueEx(key, "EndTimeLo")
    except OSError:
        return None
    ticks = (int(high) << 32) | (int(low) & 0xFFFFFFFF)
    return datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10) if ticks else None


def _policy_errors(ctx: ToolContext) -> tuple[int, str | None]:
    query = (
        "*[System[Provider[@Name='Microsoft-Windows-GroupPolicy'] and (Level=1 or Level=2) "
        "and TimeCreated[timediff(@SystemTime) <= 86400000]]]"
    )
    output = ctx.command(
        [WEVTUTIL, "qe", "System", f"/q:{query}", "/c:20", "/rd:true", "/f:text"],
        timeout_s=30,
        quiet=True,
    )
    if not output.ok:
        return 0, None
    events = output.stdout.count("Event[")
    descriptions = re.findall(r"(?:Description|Descripción):\s*\n?(.+)", output.stdout)
    return events, (descriptions[0].strip()[:300] if descriptions else None)


def _diagnose(params: Params, ctx: ToolContext) -> ToolResult:
    checks = []
    joined, domain = membership()
    checks.append(
        check("El equipo pertenece a un dominio", joined, domain or "Está en un grupo de trabajo")
    )
    if not joined or not domain:
        return ToolResult(checks=checks, summary=[fact("Dominio", None)])
    ctx.progress(1, 8, "DNS")
    try:
        addresses = sorted(
            {str(info[4][0]) for info in socket.getaddrinfo(domain, None, socket.AF_INET)}
        )
        checks.append(check("El DNS resuelve el dominio", True, ", ".join(addresses[:5])))
    except OSError:
        checks.append(
            check(
                "El DNS resuelve el dominio",
                False,
                "El servidor DNS del equipo no conoce el dominio",
                link("network.flush_dns", "Vaciar caché DNS"),
            )
        )
    ctx.progress(2, 8, "Controlador de dominio")
    dc, code = find_domain_controller(domain, rediscover=bool(params.get("rediscover")))
    if dc is None:
        checks.append(
            check(
                "Se encuentra un controlador de dominio",
                False,
                f"DsGetDcName devolvió {code} (sin red al dominio, DNS o VPN)",
                link("network.diagnose", "Diagnosticar la red"),
            )
        )
        return ToolResult(checks=checks, summary=[fact("Dominio", domain)])
    checks.append(
        check(
            "Se encuentra un controlador de dominio",
            True,
            f"{dc.name} ({dc.address}), sitio {dc.site or '?'}",
        )
    )
    ctx.progress(3, 8, "Puertos")
    host = dc.address or dc.name
    closed = [f"{port} {label}" for port, label in _PORTS if not tcp_port_open(host, port)]
    checks.append(
        check(
            "Puertos del controlador abiertos",
            not closed,
            "Cerrados: " + ", ".join(closed)
            if closed
            else "53, 88, 135, 389, 445 y 3268 responden",
            warn=len(closed) < 3,
        )
    )
    ctx.progress(4, 8, "Hora")
    offset = remote_time_offset(dc.name)
    if offset is None:
        checks.append(
            check(
                "Hora sincronizada con el controlador",
                None,
                "No se pudo leer la hora del controlador",
            )
        )
    else:
        ok = abs(offset) < _MAX_SKEW_S
        checks.append(
            check(
                "Hora sincronizada con el controlador",
                ok,
                f"Diferencia de {offset:+.0f} s"
                + ("" if ok else ": Kerberos rechaza más de 5 minutos"),
                None if ok else link("domain.time_resync", "Sincronizar hora", Tone.WARN),
            )
        )
    ctx.progress(5, 8, "Canal seguro")
    if ctx.env.is_elevated:
        output = ctx.command([NLTEST, f"/sc_query:{domain}"], timeout_s=60, quiet=True)
        ok = output.ok and "0x0" in output.stdout
        checks.append(
            check(
                "Canal seguro con el dominio",
                ok,
                "Correcto" if ok else output.text[-300:],
                None
                if ok
                else link("domain.secure_channel_reset", "Restablecer canal seguro", Tone.WARN),
            )
        )
    else:
        checks.append(
            check("Canal seguro con el dominio", None, "Requiere administrador para comprobarlo")
        )
    ctx.progress(6, 8, "SYSVOL")
    try:
        policies = sum(1 for _ in Path(f"\\\\{domain}\\SYSVOL\\{domain}\\Policies").iterdir())
        checks.append(check("SYSVOL accesible", True, f"{policies} directivas publicadas"))
    except OSError as error:
        checks.append(
            check(
                "SYSVOL accesible",
                False,
                f"No se pudo leer \\\\{domain}\\SYSVOL ({error.strerror or type(error).__name__})",
                link("domain.kerberos_purge", "Renovar tickets de Kerberos"),
            )
        )
    ctx.progress(7, 8, "Directivas")
    last = last_machine_policy()
    if last is None:
        checks.append(
            check(
                "Directivas de equipo aplicadas",
                False,
                "No hay registro de una aplicación",
                link("domain.gpupdate", "Aplicar directivas", Tone.WARN),
            )
        )
    else:
        age = datetime.now(UTC) - last
        checks.append(
            check(
                "Directivas de equipo aplicadas recientemente",
                age < timedelta(hours=8),
                f"Última: {last.astimezone():%Y-%m-%d %H:%M} (hace {int(age.total_seconds() // 3600)} h)",
                link("domain.gpupdate", "Aplicar directivas"),
                warn=True,
            )
        )
    errors, detail = _policy_errors(ctx)
    checks.append(
        check(
            "Sin errores de directivas en 24 h",
            errors == 0,
            detail if errors else "Sin errores en el registro de eventos",
            link("domain.gpupdate", "Aplicar directivas") if errors else None,
            warn=True,
        )
    )
    ctx.progress(8, 8)
    return ToolResult(
        summary=[
            fact("Dominio", domain),
            fact("Controlador", dc.name),
            fact("Dirección", dc.address),
            fact("Sitio", dc.client_site),
        ],
        checks=checks,
    )


diagnose = SupportTool(
    tool(
        "domain.diagnose",
        "Dominio y directivas",
        "Diagnóstico de dominio",
        "Comprueba pertenencia, DNS, controlador, puertos, hora, canal seguro, SYSVOL y directivas, y propone la corrección de cada fallo.",
        Risk.READ,
        params=[
            choice(
                "rediscover",
                "Buscar controlador",
                [("", "Usar el conocido"), ("1", "Forzar nueva búsqueda")],
            )
        ],
        network=True,
        hidden=True,
    ),
    lambda _p, _e: [
        step("Pertenencia al dominio", "systeminfo | findstr /i domain"),
        step("Resolver el dominio por DNS", "nslookup <dominio>"),
        step("Buscar controlador de dominio", "nltest /dsgetdc:<dominio>"),
        step(
            "Probar puertos 53, 88, 135, 389, 445 y 3268",
            "Test-NetConnection <controlador> -Port 389",
        ),
        step(
            "Comparar la hora con el controlador",
            "w32tm /stripchart /computer:<controlador> /samples:1",
        ),
        step("Canal seguro", "nltest /sc_query:<dominio>"),
        step("Acceso a SYSVOL", "dir \\\\<dominio>\\SYSVOL"),
        step("Última aplicación y errores de directivas", "gpresult /r"),
    ],
    _diagnose,
)


# --- gpupdate resiliente -----------------------------------------------------------------------------


def _apply(ctx: ToolContext, target: str) -> bool:
    output = ctx.command([GPUPDATE, f"/target:{target}", "/force", "/wait:600"], timeout_s=660)
    return output.ok


def _gpupdate(params: Params, ctx: ToolContext) -> ToolResult:
    joined, domain = membership()
    if not joined:
        raise ValueError("El equipo no pertenece a un dominio")
    before = last_machine_policy()
    dc, code = find_domain_controller(domain, rediscover=True)
    if dc is None:
        ctx.warn(f"No se encontró controlador (código {code}): se intenta igual tras vaciar DNS")
        flush_dns_cache()
    targets = ["computer", "user"] if params["target"] == "both" else [params["target"]]
    results = {}
    for target in targets:
        ok = _apply(ctx, target)
        if not ok:
            ctx.warn(
                "Primer intento fallido: se vacía el DNS, se renuevan los tickets de Kerberos y se reintenta"
            )
            flush_dns_cache()
            ctx.command([KLIST, "purge"], timeout_s=30, quiet=True)
            ok = _apply(ctx, target)
        results[target] = ok
    after = last_machine_policy()
    refreshed = after is not None and (before is None or after > before)
    checks = [
        check(f"Directivas de {'equipo' if t == 'computer' else 'usuario'}", ok)
        for t, ok in results.items()
    ]
    if "computer" in results:
        checks.append(
            check(
                "Windows registró una aplicación nueva",
                refreshed,
                f"Última: {after.astimezone():%Y-%m-%d %H:%M}" if after else None,
                link("domain.diagnose", "Diagnosticar dominio") if not refreshed else None,
            )
        )
    return ToolResult(
        checks=checks, verified=all(results.values()) and (refreshed or "computer" not in results)
    )


gpupdate = SupportTool(
    tool(
        "domain.gpupdate",
        "Dominio y directivas",
        "Aplicar directivas (gpupdate)",
        "Fuerza la aplicación de directivas; si falla, vacía DNS, renueva Kerberos y reintenta; verifica que Windows registró la aplicación.",
        Risk.CHANGE,
        params=[
            choice(
                "target",
                "Aplicar a",
                [
                    ("both", "Equipo y usuario"),
                    ("computer", "Solo equipo"),
                    ("user", "Solo usuario"),
                ],
            )
        ],
        network=True,
        hidden=True,
    ),
    lambda p, _e: [
        step("Comprobar el controlador de dominio", "nltest /dsgetdc:<dominio> /force"),
        *[
            step(f"Aplicar directivas de {t}", f"gpupdate /target:{t} /force /wait:600")
            for t in (["computer", "user"] if p["target"] == "both" else [p["target"]])
        ],
        step(
            "Si falla: vaciar DNS, renovar Kerberos y reintentar",
            "ipconfig /flushdns & klist purge",
        ),
        step("Verificar la hora de la última aplicación", "gpresult /r"),
    ],
    _gpupdate,
    warnings=lambda _p, _e: [
        "Algunas directivas piden cerrar sesión o reiniciar: gpupdate no reinicia el equipo."
    ],
)


# --- Hora, Kerberos y canal seguro ---------------------------------------------------------------


def _time(_params: Params, ctx: ToolContext) -> ToolResult:
    def resync() -> bool:
        return ctx.command([W32TM, "/resync", "/force"], timeout_s=60).ok

    def restart_and_resync() -> bool:
        stop_service(ctx, "w32time")
        start_service(ctx, "w32time")
        return ctx.command([W32TM, "/resync", "/rediscover"], timeout_s=60).ok

    way = first_that_works(
        ctx,
        [
            Attempt("w32tm /resync /force", resync),
            Attempt("reiniciar w32time y resincronizar", restart_and_resync),
        ],
    )
    joined, domain = membership()
    offset = None
    if joined and domain:
        dc, _ = find_domain_controller(domain)
        offset = remote_time_offset(dc.name) if dc else None
    ok = way is not None and (offset is None or abs(offset) < _MAX_SKEW_S)
    return ToolResult(
        checks=[
            check(
                "Hora sincronizada",
                ok,
                f"Diferencia con el controlador: {offset:+.0f} s" if offset is not None else None,
            )
        ],
        verified=ok,
    )


time_resync = SupportTool(
    tool(
        "domain.time_resync",
        "Dominio y directivas",
        "Sincronizar la hora",
        "Resincroniza la hora con su fuente (dominio o NTP) y verifica la diferencia.",
        Risk.CHANGE,
        admin=True,
        hidden=True,
    ),
    lambda _p, _e: [
        step("Resincronizar", "w32tm /resync /force"),
        step(
            "Si falla: reiniciar el servicio y redescubrir la fuente",
            "net stop w32time & net start w32time & w32tm /resync /rediscover",
        ),
    ],
    _time,
)


def _kerberos(_params: Params, ctx: ToolContext) -> ToolResult:
    user = ctx.command([KLIST, "purge"], timeout_s=30)
    checks = [check("Tickets del usuario renovados", user.ok)]
    if ctx.env.is_elevated:
        machine = ctx.command([KLIST, "-li", "0x3e7", "purge"], timeout_s=30)
        checks.append(check("Tickets del equipo renovados", machine.ok))
    else:
        checks.append(check("Tickets del equipo", None, "Requiere administrador"))
    return ToolResult(checks=checks, verified=user.ok)


kerberos = SupportTool(
    tool(
        "domain.kerberos_purge",
        "Dominio y directivas",
        "Renovar tickets de Kerberos",
        "Descarta los tickets en caché para que Windows pida unos nuevos al controlador.",
        Risk.CHANGE,
        hidden=True,
    ),
    lambda _p, _e: [
        step("Tickets del usuario", "klist purge"),
        step("Tickets del equipo (administrador)", "klist -li 0x3e7 purge"),
    ],
    _kerberos,
)


def _secure_channel(_params: Params, ctx: ToolContext) -> ToolResult:
    joined, domain = membership()
    if not joined or not domain:
        raise ValueError("El equipo no pertenece a un dominio")
    first_that_works(
        ctx,
        [
            Attempt(
                "nltest /sc_reset",
                lambda: ctx.command([NLTEST, f"/sc_reset:{domain}"], timeout_s=120).ok,
            ),
            Attempt(
                "Test-ComputerSecureChannel -Repair",
                lambda: (
                    powershell(
                        ctx,
                        "if (Test-ComputerSecureChannel -Repair) { exit 0 } else { exit 1 }",
                        timeout_s=180,
                    ).ok
                ),
            ),
        ],
    )
    verify = ctx.command([NLTEST, f"/sc_verify:{domain}"], timeout_s=120)
    ok = verify.ok and "0x0" in verify.stdout
    return ToolResult(
        checks=[check("Canal seguro verificado", ok, verify.text[-300:] if not ok else None)],
        verified=ok,
    )


secure_channel = SupportTool(
    tool(
        "domain.secure_channel_reset",
        "Dominio y directivas",
        "Restablecer canal seguro",
        "Restablece la relación de confianza del equipo con el dominio y la verifica.",
        Risk.CHANGE,
        admin=True,
        network=True,
        hidden=True,
    ),
    lambda _p, _e: [
        step("Restablecer", "nltest /sc_reset:<dominio>"),
        step("Si falla", "Test-ComputerSecureChannel -Repair"),
        step("Verificar", "nltest /sc_verify:<dominio>"),
    ],
    _secure_channel,
)

TOOLS = [diagnose, gpupdate, time_resync, kerberos, secure_channel]
