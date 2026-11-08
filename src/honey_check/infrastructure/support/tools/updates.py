"""«Windows Update no actualiza»: causa por servicio, directiva, reinicio pendiente, espacio o el
código de error que dejó Windows Update; arreglo solo de esa causa; verificación buscando
actualizaciones de verdad.

La revisión previa es rápida (servicios, directivas, reinicio, espacio, errores recientes del
registro de eventos). Al ejecutar se corrige lo encontrado y se busca actualizaciones con la API de
Windows Update: si la búsqueda falla, su código decide el arreglo siguiente (caché dañada →
renovarla; almacén de componentes → DISM) y se vuelve a buscar. Las directivas de la empresa
(WSUS, acceso bloqueado) se muestran y nunca se cambian.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import winreg
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from honey_check.application.ports import CancelToken
from honey_check.application.support.ports import CommandOutput, SupportEnvironment, ToolContext
from honey_check.domain.support import Check, CheckStatus, Risk, ToolResult
from honey_check.infrastructure.windows.netdiag import tcp_port_open

from ..base import Params, SupportTool, fact, link, step, tool
from ..runner import tool_path
from ..winops import powershell

SC = tool_path("sc.exe")
DISM = tool_path("dism.exe")
WEVTUTIL = tool_path("wevtutil.exe")
_CORE = ("wuauserv", "bits", "cryptsvc")
_RESET = ("wuauserv", "bits", "cryptsvc", "msiserver")
_MIN_FREE = 10 * 1024**3
_SEARCH_TIMEOUT_S = 240
_EVENT_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

# Código de error de Windows Update → (qué significa, arreglo o None si no depende del equipo).
_CODES: dict[int, tuple[str, str | None]] = {
    0x80070422: ("Un servicio de Windows Update está deshabilitado", "services"),
    0x80070002: ("Faltan archivos de la caché de Windows Update", "cache"),
    0x80070003: ("Faltan archivos de la caché de Windows Update", "cache"),
    0x8007000D: ("La caché de Windows Update está dañada", "cache"),
    0x80248007: ("La base de datos de Windows Update está dañada", "cache"),
    0x8024A105: ("La caché de Windows Update está dañada", "cache"),
    0x80240034: ("La descarga quedó incompleta", "cache"),
    0x80246007: ("La descarga quedó incompleta", "cache"),
    0x80246008: ("BITS no pudo descargar la actualización", "cache"),
    0x80073712: ("El almacén de componentes de Windows está dañado", "dism"),
    0x800F081F: ("Faltan archivos de origen en el almacén de componentes", "dism"),
    0x800F0831: ("Falta un paquete previo en el almacén de componentes", "dism"),
    0x80070070: ("No hay espacio suficiente en el disco", None),
    0x80070112: ("No hay espacio suficiente en el disco", None),
    0x800F0922: ("La partición reservada del sistema está llena o falló .NET", None),
    0x8024402C: ("No se pudo conectar: proxy o red", None),
    0x80072EE2: ("Se agotó el tiempo al conectar con Windows Update", None),
    0x80072EFD: ("No se pudo conectar con Windows Update", None),
    0x80072F8F: ("La hora del equipo está mal o falló la conexión segura", None),
    0x80244022: ("El servidor de actualizaciones está ocupado; reintente más tarde", None),
    0x8024401C: ("El servidor de actualizaciones no respondió a tiempo", None),
    0x80070643: ("Falló el instalador de la actualización (MSI o .NET)", "cache"),
    0x80073D02: ("Una aplicación de la Tienda no se actualizó porque estaba abierta", None),
    0x80073CF9: ("Una aplicación de la Tienda no se pudo instalar", None),
}
# Las aplicaciones de la Tienda se identifican así («9NKSQGP7F2NH-…»): no son de Windows Update.
_STORE_APP = re.compile(r"^9[A-Z0-9]{11}-")


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def explain(code: int) -> tuple[str, str | None]:
    """Un código desconocido no dispara ningún arreglo: se muestra tal cual."""
    return _CODES.get(code, ("Windows Update devolvió un error que Honey Check no reconoce", None))


# --- Lo que se lee del equipo (funciones de módulo: las pruebas las simulan) -------------------


def _run(env: SupportEnvironment, args: list[str], timeout_s: float = 20) -> CommandOutput:
    return env.runner.run(args, timeout_s=timeout_s, cancel=CancelToken())


@dataclass(frozen=True)
class Service:
    name: str
    running: bool
    disabled: bool


_STATE = re.compile(r"(\d)\s+(RUNNING|STOPPED|START_PENDING|STOP_PENDING|PAUSED)")


def start_type(name: str) -> int | None:
    """Tipo de inicio desde el Registro (4 = deshabilitado): no depende del idioma de Windows."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{name}"
        ) as key:
            return int(winreg.QueryValueEx(key, "Start")[0])
    except (OSError, ValueError):
        return None


def service(env: SupportEnvironment, name: str) -> Service:
    match = _STATE.search(_run(env, [SC, "query", name]).stdout)
    return Service(
        name=name,
        running=bool(match and match.group(2) == "RUNNING"),
        disabled=start_type(name) == 4,
    )


@dataclass(frozen=True)
class UpdatePolicy:
    wsus: str | None = None
    user_access_blocked: bool = False
    automatic_disabled: bool = False


def update_policy() -> UpdatePolicy:
    base = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"

    def value(sub: str, name: str) -> object:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    wsus = value(base, "WUServer") if value(base + r"\AU", "UseWUServer") == 1 else None
    return UpdatePolicy(
        wsus=str(wsus) if wsus else None,
        user_access_blocked=value(base, "DisableWindowsUpdateAccess") == 1,
        automatic_disabled=value(base + r"\AU", "NoAutoUpdate") == 1,
    )


def pending_reboot() -> list[str]:
    reasons = []
    for sub, why in (
        (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
            "actualizaciones de Windows",
        ),
        (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
            "Windows Update",
        ),
    ):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub))
            reasons.append(why)
        except OSError:
            continue
    return reasons


def system_free_bytes() -> int:
    return shutil.disk_usage(os.environ.get("SYSTEMDRIVE", "C:") + "\\").free


@dataclass(frozen=True)
class UpdateError:
    code: int
    title: str
    at: datetime


def update_errors(env: SupportEnvironment, days: int = 7) -> list[UpdateError]:
    query = (
        "*[System[Provider[@Name='Microsoft-Windows-WindowsUpdateClient'] and Level=2 and "
        f"TimeCreated[timediff(@SystemTime) <= {days * 86_400_000}]]]"
    )
    output = _run(env, [WEVTUTIL, "qe", "System", f"/q:{query}", "/c:10", "/rd:true", "/f:xml"], 20)
    if not output.ok or not output.stdout.strip():
        return []
    try:
        root = ElementTree.fromstring(f"<eventos>{output.stdout}</eventos>")  # noqa: S314 - salida local de wevtutil
    except ElementTree.ParseError:
        return []
    errors = []
    for event in root.findall("e:Event", _EVENT_NS):
        data = {
            item.get("Name"): (item.text or "")
            for item in event.findall("e:EventData/e:Data", _EVENT_NS)
        }
        code = data.get("errorCode") or ""
        if not code.lower().startswith("0x"):
            continue
        created = event.find("e:System/e:TimeCreated", _EVENT_NS)
        stamp = created.get("SystemTime", "") if created is not None else ""
        try:
            at = datetime.fromisoformat(stamp[:19]).replace(tzinfo=UTC)
        except ValueError:
            at = datetime.now(UTC)
        errors.append(UpdateError(int(code, 16), data.get("updateTitle") or "", at))
    return errors


def endpoint_reachable(policy: UpdatePolicy) -> tuple[str, bool]:
    if policy.wsus:
        url = urlparse(policy.wsus)
        host = url.hostname or policy.wsus
        port = url.port or (443 if url.scheme == "https" else 8530)
        return f"{host}:{port}", tcp_port_open(host, port, 3.0)
    for host in ("download.windowsupdate.com", "fe2.update.microsoft.com"):
        if tcp_port_open(host, 443, 3.0):
            return host, True
    return "servidores de Microsoft", False


_SEARCH = (
    "$ErrorActionPreference='Stop'; try { "
    "$s = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher(); "
    "$r = $s.Search('IsInstalled=0 and IsHidden=0'); "
    "@{ok=($r.ResultCode -eq 2); count=$r.Updates.Count; code=0} | ConvertTo-Json -Compress "
    "} catch { @{ok=$false; count=0; code=$_.Exception.HResult} | ConvertTo-Json -Compress }"
)


def search_updates(ctx: ToolContext) -> tuple[bool, int, int]:
    """Busca de verdad con la API de Windows Update: (funcionó, pendientes, código de error)."""
    ctx.progress(0, 0, "Buscando actualizaciones con Windows Update (hasta 4 minutos)")
    output = powershell(ctx, _SEARCH, timeout_s=_SEARCH_TIMEOUT_S)
    try:
        data = json.loads(output.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, 0, 0
    return (
        bool(data.get("ok")),
        int(data.get("count") or 0),
        int(data.get("code") or 0) & 0xFFFFFFFF,
    )


# --- Diagnóstico -------------------------------------------------------------------------------


@dataclass
class Finding:
    key: str
    label: str
    status: CheckStatus
    detail: str
    fix: str | None = None
    technical: str | None = None

    def check(self) -> Check:
        return Check(
            label=self.label, status=self.status, detail=self.detail, technical=self.technical
        )


@dataclass
class Diagnosis:
    findings: list[Finding] = field(default_factory=list)
    policy: UpdatePolicy = field(default_factory=UpdatePolicy)

    @property
    def fixes(self) -> list[str]:
        return list(dict.fromkeys(f.fix for f in self.findings if f.fix))

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.status is CheckStatus.FAIL and not f.fix]


def diagnose(env: SupportEnvironment) -> Diagnosis:
    found = Diagnosis(policy=update_policy())
    add = found.findings.append
    policy = found.policy

    disabled = [s for s in (service(env, name) for name in _CORE) if s.disabled]
    if disabled:
        names = ", ".join(s.name for s in disabled)
        if policy.automatic_disabled:
            add(
                Finding(
                    "services",
                    "Servicios deshabilitados",
                    CheckStatus.FAIL,
                    f"{names} deshabilitado por una directiva de la empresa: no se cambia.",
                )
            )
        else:
            add(
                Finding(
                    "services",
                    "Servicios deshabilitados",
                    CheckStatus.WARN,
                    f"{names} está deshabilitado y Windows Update no puede funcionar. Se "
                    "vuelve a habilitar (inicio manual, como viene Windows).",
                    fix="services",
                )
            )
    else:
        add(
            Finding(
                "services",
                "Servicios",
                CheckStatus.OK,
                "Windows Update, BITS y criptografía habilitados",
            )
        )

    if policy.wsus:
        add(
            Finding(
                "policy",
                "Servidor de la empresa (WSUS)",
                CheckStatus.INFO,
                f"Las actualizaciones vienen de {policy.wsus}, no de Microsoft.",
            )
        )
    if policy.user_access_blocked:
        add(
            Finding(
                "access",
                "Acceso del usuario bloqueado",
                CheckStatus.INFO,
                "Una directiva oculta Windows Update al usuario; Honey Check igual puede "
                "buscar e instalar como administrador.",
            )
        )

    target, reachable = endpoint_reachable(policy)
    if reachable:
        add(Finding("network", "Conexión", CheckStatus.OK, f"Responde {target}"))
    else:
        add(
            Finding(
                "network",
                "Conexión",
                CheckStatus.FAIL,
                f"No responde {target}: sin internet, proxy o firewall. Revise la red primero.",
            )
        )

    reboot = pending_reboot()
    if reboot:
        add(
            Finding(
                "reboot",
                "Reinicio pendiente",
                CheckStatus.WARN,
                f"Windows espera un reinicio ({', '.join(reboot)}) y no instala más hasta "
                "entonces. Reinicie después de esto.",
            )
        )

    free = system_free_bytes()
    if free < _MIN_FREE:
        add(
            Finding(
                "space",
                "Poco espacio",
                CheckStatus.FAIL,
                f"Quedan {free / 1024**3:.1f} GiB en el disco del sistema; las actualizaciones "
                "grandes necesitan unos 10. Libere espacio primero.",
            )
        )

    all_errors = update_errors(env)
    store = [e for e in all_errors if _STORE_APP.match(e.title)]
    errors = [e for e in all_errors if not _STORE_APP.match(e.title)]
    if store:
        add(
            Finding(
                "store",
                "Aplicaciones de la Tienda",
                CheckStatus.INFO,
                f"{_count(len(store), 'actualización', 'actualizaciones')} de aplicaciones de la "
                f"Tienda {'falló' if len(store) == 1 else 'fallaron'}. No es "
                "Windows Update: se reintentan solas cuando la aplicación está cerrada.",
                technical=", ".join(f"0x{e.code:08X} {e.title}" for e in store[:3]),
            )
        )
    if errors:
        newest = errors[0]
        meaning, fix = explain(newest.code)
        add(
            Finding(
                "errors",
                f"Error 0x{newest.code:08X}",
                CheckStatus.WARN,
                f"{meaning} ({newest.at.astimezone():%d/%m %H:%M}"
                + (f", «{newest.title[:60]}»" if newest.title else "")
                + ")."
                + (" Se corrige." if fix else ""),
                fix=fix,
                technical=f"0x{newest.code:08X} {newest.title}",
            )
        )
    else:
        add(
            Finding(
                "errors", "Errores recientes", CheckStatus.OK, "Sin errores en los últimos 7 días"
            )
        )
    return found


# --- Revisión y arreglos -------------------------------------------------------------------------

_VERBS = {
    "services": "habilitar los servicios",
    "cache": "renovar la caché de Windows Update",
    "dism": "reparar el almacén de componentes con DISM (puede tardar 15 minutos)",
}


def _review(_params: Params, env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    found = diagnose(env)
    checks = [f.check() for f in found.findings]
    if found.blocking:
        return f"{found.blocking[0].detail.split(':')[0]}. Resuélvalo primero.", checks, False
    if found.fixes:
        verbs = [_VERBS[f] for f in found.fixes]
        what = verbs[0] if len(verbs) == 1 else f"{', '.join(verbs[:-1])} y {verbs[-1]}"
        return (
            f"Se va a {what}. Después se buscan actualizaciones para comprobar que funciona.",
            checks,
            True,
        )
    return (
        "No se ve una causa en el equipo. Se buscan actualizaciones de verdad; si falla, su código "
        "dice qué corregir y se corrige.",
        checks,
        True,
    )


def _wait_state(env: SupportEnvironment, name: str, running: bool, timeout_s: float = 30) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if service(env, name).running is running:
            return True
        _pause(1)
    return False


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def _fix_services(ctx: ToolContext) -> Check:
    changed = []
    for name in _CORE:
        if service(ctx.env, name).disabled:
            ctx.command([SC, "config", name, "start=", "demand"], timeout_s=30)
            changed.append(name)
    ok = all(not service(ctx.env, name).disabled for name in _CORE)
    return Check(
        label="Habilitar servicios",
        status=CheckStatus.OK if ok else CheckStatus.FAIL,
        detail=f"{', '.join(changed)} con inicio manual"
        if ok
        else "Windows no permitió cambiarlos",
        technical="Antes: deshabilitado (sc config <servicio> start= disabled para volver)",
    )


def _fix_cache(ctx: ToolContext) -> Check:
    windows = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows")
    for name in _RESET:
        ctx.command([SC, "stop", name], timeout_s=30, quiet=True)
    stopped = all(_wait_state(ctx.env, name, False) for name in ("wuauserv", "bits"))
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    renamed = []
    try:
        for folder in (windows / "SoftwareDistribution", windows / "System32" / "catroot2"):
            if folder.exists():
                target = folder.with_name(f"{folder.name}.old-{stamp}")
                try:
                    folder.rename(target)
                    renamed.append(target.name)
                except OSError as error:
                    ctx.warn(f"No se pudo renombrar {folder.name}: {error.strerror}")
    finally:
        for name in ("cryptsvc", "bits", "wuauserv"):
            ctx.command([SC, "start", name], timeout_s=30, quiet=True)
    ok = stopped and len(renamed) == 2
    return Check(
        label="Renovar la caché de Windows Update",
        status=CheckStatus.OK if ok else CheckStatus.FAIL,
        detail="SoftwareDistribution y catroot2 renovadas; las anteriores quedan renombradas"
        if ok
        else "Algún servicio no se detuvo o una carpeta siguió en uso",
        technical=", ".join(renamed) or None,
    )


def _fix_dism(ctx: ToolContext) -> Check:
    ctx.progress(0, 0, "Reparando el almacén de componentes (DISM, hasta 30 minutos)")
    output = ctx.command(
        [DISM, "/Online", "/Cleanup-Image", "/RestoreHealth", "/NoRestart"], timeout_s=3600
    )
    return Check(
        label="Reparar el almacén de componentes",
        status=CheckStatus.OK if output.ok else CheckStatus.FAIL,
        detail="DISM terminó sin errores" if output.ok else "DISM no pudo repararlo",
        technical=None if output.ok else output.text[-300:],
    )


_FIXERS = {"services": _fix_services, "cache": _fix_cache, "dism": _fix_dism}


def _updates(_params: Params, ctx: ToolContext) -> ToolResult:
    found = diagnose(ctx.env)
    if found.blocking:
        raise ValueError(found.blocking[0].detail)
    applied: list[Check] = []
    done: set[str] = set()
    pending = list(found.fixes)
    ok, count, code = False, 0, 0
    # Arreglar lo visto, buscar; si la búsqueda falla, su código decide el siguiente arreglo.
    for _round in range(3):
        for key in pending:
            if key in done:
                continue
            done.add(key)
            ctx.info(f"Corrigiendo: {_VERBS[key]}")
            applied.append(_FIXERS[key](ctx))
        ok, count, code = search_updates(ctx)
        if ok:
            break
        meaning, fix = explain(code)
        ctx.warn(f"La búsqueda falló: {meaning} (0x{code:08X})")
        if not fix or fix in done:
            break
        pending = [fix]
    checks = [*applied]
    if ok:
        checks.append(
            Check(
                label="Windows Update responde",
                status=CheckStatus.OK,
                detail=f"La búsqueda funcionó: {count} actualizaciones pendientes"
                if count
                else "La búsqueda funcionó: el equipo está al día",
            )
        )
    else:
        meaning, _fix = explain(code)
        checks.append(
            Check(
                label="Windows Update responde",
                status=CheckStatus.FAIL,
                detail=f"La búsqueda sigue fallando: {meaning}.",
                technical=f"0x{code:08X}" if code else None,
                fix=link("network.connectivity", "Revisar la red")
                if code in (0x8024402C, 0x80072EE2, 0x80072EFD)
                else None,
            )
        )
    reboot = pending_reboot()
    return ToolResult(
        summary=[
            fact("Pendientes", count if ok else None),
            *([fact("Reinicio", "Pendiente: reinicie para terminar")] if reboot else []),
        ],
        checks=checks,
        verified=ok,
    )


updates = SupportTool(
    tool(
        "system.updates",
        "Sistema",
        "Windows Update no actualiza",
        "Encuentra la causa (servicios, directivas, conexión, reinicio, espacio o el código de "
        "error de Windows Update), corrige solo esa y comprueba buscando actualizaciones.",
        Risk.CHANGE,
        admin=True,
        network=True,
        action="Corregir Windows Update",
    ),
    lambda _p, _e: [
        step("Servicios y su tipo de inicio", "sc qc wuauserv"),
        step(
            "Directivas de la empresa (solo lectura)",
            r"reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate",
        ),
        step(
            "Errores recientes", "Get-WinEvent -ProviderName Microsoft-Windows-WindowsUpdateClient"
        ),
        step(
            "Corregir: servicios, caché (SoftwareDistribution y catroot2) o DISM",
            "DISM /Online /Cleanup-Image /RestoreHealth",
        ),
        step("Buscar actualizaciones con la API de Windows Update para comprobar"),
    ],
    _updates,
    review=_review,
)

TOOLS = [updates]
