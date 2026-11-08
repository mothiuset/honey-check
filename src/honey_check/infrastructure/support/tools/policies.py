"""«Las directivas no se aplican»: diagnóstico en paralelo, arreglo solo de la causa y verificación.

La revisión previa ya es el diagnóstico (segundos, cada prueba con su límite de tiempo): el
técnico ve la causa antes de pulsar nada. Al ejecutar se corrige únicamente lo encontrado, en
orden (hora, canal seguro, tickets de Kerberos, Registry.pol dañado), después se aplican las
directivas con un límite corto y se verifica con el registro de eventos. Lo que no se puede
arreglar desde el equipo (sin red al controlador, puertos cerrados) bloquea el botón y dice qué
revisar.

Registry.pol es el único archivo de directivas que Honey Check toca, y solo si su cabecera es
inválida o Windows registró el evento 1096: se respalda y se renombra para que Windows lo vuelva a
generar desde el dominio. Nunca se escribe su contenido ni claves de directivas.
"""

from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from honey_check.application.ports import CancelToken
from honey_check.application.support.ports import CommandOutput, SupportEnvironment, ToolContext
from honey_check.domain.support import ActionLink, Check, CheckStatus, Risk, ToolResult
from honey_check.infrastructure.windows.netdiag import (
    DomainController,
    find_domain_controller,
    remote_time_offset,
    tcp_port_open,
)
from honey_check.infrastructure.windows.session import current_user_sid

from ..base import Params, SupportTool, choice, fact, link, step, tool
from ..runner import tool_path
from . import domain

REGISTRY_POL_HEADER = b"PReg\x01\x00\x00\x00"
_CHECK_BUDGET_S = 8.0
_APPLY_TIMEOUT_S = 150
_PORTS = ((88, "Kerberos"), (389, "LDAP"), (445, "SYSVOL"))
_EVENT_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
# Eventos de directivas en el registro System y qué significan para el técnico.
_EVENTS = {
    1096: "Registry.pol dañado: Windows no puede leer las directivas guardadas en el equipo",
    1058: "No se pudo leer gpt.ini de una directiva en SYSVOL (red, DFS o permisos)",
    1030: "No se pudo obtener la lista de directivas del controlador",
    1129: "Sin conexión con el controlador de dominio al aplicar directivas",
    1053: "No se pudo resolver el usuario o el equipo en el dominio",
    1054: "No se pudo obtener el nombre del controlador de dominio",
    1055: "No se pudo resolver el nombre del equipo en el dominio",
    1085: "Una extensión de directivas falló al aplicar su parte",
}
_POL = re.compile(r"[A-Za-z]:\\[^\r\n\"]*?registry\.pol", re.IGNORECASE)


def registry_pol(scope: str) -> Path:
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return Path(root) / "System32" / "GroupPolicy" / scope / "Registry.pol"


def pol_is_damaged(path: Path) -> bool | None:
    """True si existe y su cabecera no es la de un Registry.pol; None si no se pudo leer."""
    try:
        with path.open("rb") as handle:
            header = handle.read(len(REGISTRY_POL_HEADER))
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return header != REGISTRY_POL_HEADER


# --- Diagnóstico ------------------------------------------------------------------------------


@dataclass
class Finding:
    key: str
    label: str
    status: CheckStatus
    detail: str
    fix: str | None = None  # arreglo que se aplica al ejecutar
    technical: str | None = None
    link: ActionLink | None = None

    def check(self) -> Check:
        return Check(
            label=self.label,
            status=self.status,
            detail=self.detail,
            fix=self.link,
            technical=self.technical,
        )


@dataclass
class Diagnosis:
    joined: bool
    domain: str | None
    dc: DomainController | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def fixes(self) -> list[Finding]:
        return [f for f in self.findings if f.fix]

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.status is CheckStatus.FAIL and not f.fix]


def _ok(key: str, label: str, detail: str) -> Finding:
    return Finding(key, label, CheckStatus.OK, detail)


def _run(env: SupportEnvironment, args: list[str], timeout_s: float) -> CommandOutput:
    return env.runner.run(args, timeout_s=timeout_s, cancel=CancelToken())


def _ports(host: str) -> Finding:
    with ThreadPoolExecutor(len(_PORTS)) as pool:
        open_ = dict(
            zip(_PORTS, pool.map(lambda p: tcp_port_open(host, p[0], 2.0), _PORTS), strict=True)
        )
    closed = [f"{port} ({label})" for (port, label), ok in open_.items() if not ok]
    if not closed:
        return _ok("ports", "Puertos del controlador", "88, 389 y 445 responden")
    return Finding(
        "ports",
        "Puertos del controlador",
        CheckStatus.FAIL,
        f"No responden {', '.join(closed)}: un firewall o la VPN los bloquea. Sin ellos las "
        "directivas no se pueden descargar; esto no se arregla desde este equipo.",
        link=link("network.diagnose", "Diagnosticar la red"),
    )


def _time(dc: DomainController) -> Finding:
    offset = remote_time_offset(dc.name)
    if offset is None:
        return Finding("time", "Hora", CheckStatus.INFO, "No se pudo leer la hora del controlador")
    if abs(offset) < 300:
        return _ok("time", "Hora", f"Diferencia con el controlador: {offset:+.0f} s")
    minutes = abs(offset) / 60
    return Finding(
        "time",
        "Hora desfasada",
        CheckStatus.WARN,
        f"{minutes:.0f} min de diferencia con el controlador: Kerberos rechaza más de 5. "
        "Se sincroniza con el dominio.",
        fix="time",
    )


def _sysvol(domain_name: str) -> Finding:
    try:
        count = sum(
            1 for _ in Path(f"\\\\{domain_name}\\SYSVOL\\{domain_name}\\Policies").iterdir()
        )
    except OSError as error:
        return Finding(
            "sysvol",
            "SYSVOL",
            CheckStatus.WARN,
            "No se pudo leer la carpeta de directivas del dominio. Se renuevan los tickets de "
            "Kerberos del equipo y del usuario.",
            fix="kerberos",
            technical=f"{error.strerror or type(error).__name__} ({error.winerror})"
            if getattr(error, "winerror", None)
            else None,
        )
    return _ok("sysvol", "SYSVOL", f"Accesible, {count} directivas publicadas")


def _channel(env: SupportEnvironment, domain_name: str) -> Finding:
    if not env.is_elevated:
        return Finding(
            "channel",
            "Canal seguro",
            CheckStatus.INFO,
            "Se comprueba al empezar (necesita administrador); si está roto, se restablece.",
            fix="channel",
        )
    output = _run(env, [domain.NLTEST, f"/sc_query:{domain_name}"], 60)
    if output.ok and "0x0" in output.stdout:
        return _ok("channel", "Canal seguro", "La relación de confianza con el dominio es válida")
    return Finding(
        "channel",
        "Canal seguro roto",
        CheckStatus.WARN,
        "El equipo perdió la confianza con el dominio. Se restablece con su cuenta de equipo.",
        fix="channel",
        technical=output.text[-200:],
    )


def _pol(scope: str, label: str) -> Finding:
    path = registry_pol(scope)
    damaged = pol_is_damaged(path)
    if damaged:
        return Finding(
            f"pol_{scope.lower()}",
            f"Registry.pol de {label} dañado",
            CheckStatus.WARN,
            "Su cabecera no es válida y Windows deja de aplicar las directivas. Se respalda y se "
            "renombra para que Windows lo genere de nuevo.",
            fix=f"pol_{scope.lower()}",
            technical=str(path),
        )
    if damaged is None:
        return Finding(
            f"pol_{scope.lower()}", f"Registry.pol de {label}", CheckStatus.INFO, "No se pudo leer"
        )
    return _ok(f"pol_{scope.lower()}", f"Registry.pol de {label}", "Íntegro o sin directivas")


@dataclass(frozen=True)
class PolicyEvent:
    id: int
    at: datetime
    message: str


def policy_errors(env: SupportEnvironment, since_hours: int = 24) -> list[PolicyEvent]:
    """Errores de directivas en el registro System (legible sin administrador), más reciente primero."""
    query = (
        "*[System[Provider[@Name='Microsoft-Windows-GroupPolicy'] and (Level=1 or Level=2) and "
        f"TimeCreated[timediff(@SystemTime) <= {since_hours * 3_600_000}]]]"
    )
    output = _run(
        env,
        [domain.WEVTUTIL, "qe", "System", f"/q:{query}", "/c:20", "/rd:true", "/f:RenderedXml"],
        20,
    )
    return parse_events(output.stdout) if output.ok else []


def parse_events(xml_text: str) -> list[PolicyEvent]:
    if not xml_text.strip():
        return []
    try:
        # Salida de wevtutil del propio equipo, sin DTD; expat ya limita la expansión de entidades.
        root = ElementTree.fromstring(f"<eventos>{xml_text}</eventos>")  # noqa: S314
    except ElementTree.ParseError:
        return []
    events = []
    for event in root.findall("e:Event", _EVENT_NS):
        event_id = event.findtext("e:System/e:EventID", default="0", namespaces=_EVENT_NS)
        created = event.find("e:System/e:TimeCreated", _EVENT_NS)
        stamp = created.get("SystemTime", "") if created is not None else ""
        try:
            # «2026-11-06T21:30:12.1234567Z»: siempre UTC; los segundos bastan.
            at = datetime.fromisoformat(stamp[:19]).replace(tzinfo=UTC)
        except ValueError:
            at = datetime.now(UTC)
        message = event.findtext("e:RenderingInfo/e:Message", default="", namespaces=_EVENT_NS)
        events.append(PolicyEvent(int(event_id or 0), at, " ".join(message.split())))
    return events


def _events(env: SupportEnvironment) -> list[Finding]:
    errors = policy_errors(env)
    last = domain.last_machine_policy()
    # Un error anterior a la última aplicación correcta ya no es la causa.
    current = [e for e in errors if last is None or e.at > last]
    if not current:
        return [_ok("events", "Errores de directivas", "Sin errores desde la última aplicación")]
    findings = []
    newest = current[0]
    if any(e.id == 1096 for e in current):
        path = next((m.group(0) for e in current if (m := _POL.search(e.message))), None)
        scope = "user" if path and "\\user\\" in path.lower() else "machine"
        findings.append(
            Finding(
                f"pol_{scope}",
                f"Registry.pol de {'usuario' if scope == 'user' else 'equipo'} dañado",
                CheckStatus.WARN,
                "Windows registró el evento 1096: no puede leer las directivas guardadas. Se "
                "respalda y se renombra para que Windows lo genere de nuevo.",
                fix=f"pol_{scope}",
                technical=path or newest.message[:300],
            )
        )
    meaning = _EVENTS.get(newest.id)
    if newest.id != 1096:
        findings.append(
            Finding(
                "events",
                f"Error de directivas {newest.id}",
                CheckStatus.WARN,
                (meaning or "Windows registró un error al aplicar directivas")
                + f" ({newest.at.astimezone():%d/%m %H:%M}).",
                technical=newest.message[:400],
            )
        )
    return findings


def _service(env: SupportEnvironment) -> Finding:
    output = _run(env, [tool_path("sc.exe"), "query", "gpsvc"], 15)
    running = output.ok and ("RUNNING" in output.stdout or ": 4 " in output.stdout)
    if running:
        return _ok("service", "Servicio de directivas", "En ejecución")
    return Finding(
        "service",
        "Servicio de directivas detenido",
        CheckStatus.FAIL,
        "El servicio gpsvc no está en ejecución: Windows lo maneja solo y no se puede iniciar a "
        "mano. Reinicie el equipo.",
        technical=output.text[-200:],
    )


# Orden en que se corrigen las causas: la hora primero (sin ella Kerberos rechaza todo), luego la
# confianza con el dominio, los tickets y por último Registry.pol. La lista sigue el mismo orden.
FIX_ORDER = ["time", "channel", "kerberos", "pol_machine", "pol_user"]
_KEYS = ["dc", "ports", *FIX_ORDER, "sysvol", "events", "service"]

_SEVERITY = {
    CheckStatus.FAIL: 0,
    CheckStatus.WARN: 1,
    CheckStatus.INFO: 2,
    CheckStatus.SKIPPED: 3,
    CheckStatus.OK: 4,
}


def diagnose(env: SupportEnvironment) -> Diagnosis:
    """Todas las pruebas en paralelo; la que no responde a tiempo queda como «sin respuesta»."""
    joined, domain_name = domain.membership()
    result = Diagnosis(joined=joined, domain=domain_name)
    tasks: dict[str, Callable[[], Finding | list[Finding]]] = {
        "pol_machine": lambda: _pol("Machine", "equipo"),
        "pol_user": lambda: _pol("User", "usuario"),
        "events": lambda: _events(env),
        "service": lambda: _service(env),
    }
    if not joined:
        result.findings.append(
            Finding(
                "dc",
                "Dominio",
                CheckStatus.INFO,
                f"El equipo está en el grupo de trabajo {domain_name or ''}: solo tiene directivas "
                "locales.".replace("  ", " "),
            )
        )
    if joined and domain_name:
        dc, code = find_domain_controller(domain_name)
        result.dc = dc
        if dc is None:
            result.findings.append(
                Finding(
                    "dc",
                    "Controlador de dominio",
                    CheckStatus.FAIL,
                    f"No se encuentra ningún controlador de {domain_name}: sin red al dominio, "
                    "VPN desconectada o DNS que no es el del dominio. Las directivas no se "
                    "pueden aplicar hasta resolverlo.",
                    technical=f"DsGetDcName {code}",
                    link=link("network.diagnose", "Diagnosticar la red"),
                )
            )
        else:
            result.findings.append(
                _ok("dc", "Controlador de dominio", f"{dc.name}, sitio {dc.client_site or '?'}")
            )
            host = dc.address or dc.name
            tasks["ports"] = lambda: _ports(host)
            tasks["time"] = lambda: _time(dc)
            tasks["sysvol"] = lambda: _sysvol(domain_name)
            tasks["channel"] = lambda: _channel(env, domain_name)
    pool = ThreadPoolExecutor(len(tasks))
    futures = {pool.submit(task): key for key, task in tasks.items()}
    done, pending = wait(futures, timeout=_CHECK_BUDGET_S)
    pool.shutdown(wait=False, cancel_futures=True)
    collected = list(result.findings)
    for future in done:
        try:
            value = future.result()
        except Exception as error:  # noqa: BLE001 - una prueba que falla no tumba el diagnóstico
            value = Finding(futures[future], futures[future], CheckStatus.INFO, str(error))
        collected.extend(value if isinstance(value, list) else [value])
    collected.extend(
        Finding(futures[f], futures[f], CheckStatus.INFO, "No respondió a tiempo") for f in pending
    )
    # El evento 1096 y la cabecera pueden señalar el mismo archivo: queda una fila, la más grave.
    worst: dict[str, Finding] = {}
    for finding in collected:
        kept = worst.get(finding.key)
        if kept is None or _SEVERITY[finding.status] < _SEVERITY[kept.status]:
            worst[finding.key] = finding
    result.findings = sorted(
        worst.values(),
        key=lambda f: (_SEVERITY[f.status], _KEYS.index(f.key) if f.key in _KEYS else 99),
    )
    return result


# --- Revisión previa -------------------------------------------------------------------------


def _review(_params: Params, env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    found = diagnose(env)
    checks = [f.check() for f in found.findings]
    if found.blocking:
        summary = (
            f"{found.blocking[0].detail.split('.')[0]}. Las directivas no se pueden aplicar "
            "hasta resolverlo."
        )
    elif found.fixes:
        names = [_in_sentence(f.label) for f in found.fixes if f.status is not CheckStatus.INFO]
        summary = (
            f"Se corregirá {_join(names)}. Después se aplican las directivas y se verifica el "
            "resultado."
            if names
            else "No se encontró una causa de fallo. Al empezar se comprueba el canal seguro, se "
            "aplican las directivas y se verifica el resultado."
        )
    else:
        summary = (
            "No se encontró una causa de fallo. Se aplicarán las directivas y se verificará el "
            "resultado."
        )
    return summary, checks, True


def _in_sentence(label: str) -> str:
    """«Hora desfasada» → «hora desfasada»; un nombre propio («Registry.pol…») queda igual."""
    return label if label.startswith("Registry.pol") else label[:1].lower() + label[1:]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} y {items[-1]}"


# --- Arreglos ----------------------------------------------------------------------------------


def _fix_pol(scope: str, ctx: ToolContext) -> Check:
    path = registry_pol("Machine" if scope == "machine" else "User")
    label = f"Registry.pol de {'equipo' if scope == 'machine' else 'usuario'}"
    if not path.exists():
        return Check(label=label, status=CheckStatus.SKIPPED, detail="Ya no existía")
    backup = ctx.backup_path(f"Registry.pol {scope}")
    shutil.copy2(path, backup)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path.rename(path.with_name(f"Registry.pol.dañado-{stamp}"))
    ctx.info(f"{path} respaldado en {backup} y renombrado")
    return Check(
        label=label,
        status=CheckStatus.OK,
        detail="Respaldado y renombrado: Windows lo genera de nuevo al aplicar",
        technical=str(backup),
    )


def _fix(key: str, ctx: ToolContext, domain_name: str | None) -> Check:
    if key == "time":
        result = domain.time_resync.run({}, ctx)
        return result.checks[0]
    if key == "channel" and domain_name:
        query = ctx.command([domain.NLTEST, f"/sc_query:{domain_name}"], timeout_s=60, quiet=True)
        if query.ok and "0x0" in query.stdout:
            return Check(label="Canal seguro", status=CheckStatus.OK, detail="Ya era válido")
        result = domain.secure_channel.run({}, ctx)
        outcome = result.checks[0]
        if outcome.status is CheckStatus.FAIL:
            return outcome.model_copy(
                update={
                    "detail": "No se pudo restablecer con la cuenta del equipo: hay que volver a "
                    "unirlo al dominio con un usuario del dominio."
                }
            )
        return outcome
    if key == "kerberos":
        result = domain.kerberos.run({}, ctx)
        ok = result.verified is not False
        return Check(
            label="Tickets de Kerberos",
            status=CheckStatus.OK if ok else CheckStatus.FAIL,
            detail="Renovados para el equipo y el usuario" if ok else "No se pudieron renovar",
        )
    if key in ("pol_machine", "pol_user"):
        return _fix_pol(key.removeprefix("pol_"), ctx)
    return Check(label=key, status=CheckStatus.SKIPPED, detail="Sin arreglo")


def _apply(target: str, ctx: ToolContext) -> Check:
    label = f"Directivas de {'equipo' if target == 'computer' else 'usuario'}"
    output = ctx.command(
        [domain.GPUPDATE, f"/target:{target}", "/force", f"/wait:{_APPLY_TIMEOUT_S - 30}"],
        timeout_s=_APPLY_TIMEOUT_S,
    )
    if output.ok:
        return Check(label=label, status=CheckStatus.OK, detail="Aplicadas")
    return Check(
        label=label,
        status=CheckStatus.FAIL,
        detail="Windows no terminó de aplicarlas: el error está abajo",
        technical=output.text[-300:],
    )


def _policies(params: Params, ctx: ToolContext) -> ToolResult:
    # En segundos: los eventos se leen con esa precisión y uno del mismo segundo cuenta.
    started = datetime.now(UTC).replace(microsecond=0)
    before = domain.last_machine_policy()
    found = diagnose(ctx.env)
    if found.blocking:
        raise ValueError(found.blocking[0].detail)
    checks: list[Check] = []
    for key in sorted({f.fix for f in found.fixes if f.fix}, key=FIX_ORDER.index):
        ctx.info(f"Corrigiendo: {key}")
        checks.append(_fix(key, ctx, found.domain))

    targets = ["computer", "user"] if params["target"] == "both" else [params["target"]]
    session = ctx.env.user
    if "user" in targets and session and current_user_sid() != session.sid:
        # Con credenciales de otro administrador, «usuario» sería ese administrador.
        targets.remove("user")
        checks.append(
            Check(
                label="Directivas de usuario",
                status=CheckStatus.SKIPPED,
                detail="Se aplican al volver a iniciar sesión el usuario del equipo",
            )
        )
    for target in targets:
        ctx.info(f"Aplicando directivas de {target} (hasta {_APPLY_TIMEOUT_S} s)")
        checks.append(_apply(target, ctx))

    after = domain.last_machine_policy()
    if "computer" in targets:
        refreshed = after is not None and (before is None or after > before)
        checks.append(
            Check(
                label="Windows registró la aplicación",
                status=CheckStatus.OK if refreshed else CheckStatus.FAIL,
                detail=f"A las {after.astimezone():%H:%M:%S}"
                if refreshed and after
                else "No hay registro de una aplicación nueva",
            )
        )
    new_errors = [e for e in policy_errors(ctx.env, 1) if e.at >= started]
    if new_errors:
        newest = new_errors[0]
        checks.append(
            Check(
                label=f"Error de directivas {newest.id} al aplicar",
                status=CheckStatus.FAIL,
                detail=_EVENTS.get(newest.id, "Windows registró un error al aplicar directivas"),
                technical=newest.message[:400],
            )
        )
    return ToolResult(
        summary=[
            fact("Dominio", found.domain if found.joined else "Grupo de trabajo"),
            *([fact("Controlador", found.dc.name)] if found.dc else []),
            fact("Causas corregidas", len(found.fixes)),
        ],
        checks=checks,
        verified=all(c.status is not CheckStatus.FAIL for c in checks),
    )


policies = SupportTool(
    tool(
        "domain.policies",
        "Dominio y directivas",
        "Las directivas no se aplican",
        "Busca en segundos por qué no se aplican (controlador, puertos, hora, canal seguro, "
        "SYSVOL, Registry.pol dañado, errores de Windows), corrige solo esa causa, aplica y "
        "verifica.",
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
        admin=True,
        network=True,
        action="Corregir y aplicar directivas",
    ),
    lambda p, _e: [
        step(
            "Diagnóstico en paralelo",
            "nltest /dsgetdc:<dominio>; Test-NetConnection -Port 88,389,445",
        ),
        step("Corregir la hora si difiere más de 5 min", "w32tm /resync /rediscover"),
        step("Restablecer el canal seguro si está roto", "nltest /sc_reset:<dominio>"),
        step("Renovar tickets si SYSVOL no responde", "klist purge; klist -li 0x3e7 purge"),
        step(
            "Respaldar y renombrar Registry.pol si está dañado",
            r"ren C:\Windows\System32\GroupPolicy\Machine\Registry.pol Registry.pol.dañado",
        ),
        *[
            step(f"Aplicar directivas de {t}", f"gpupdate /target:{t} /force /wait:120")
            for t in (["computer", "user"] if p["target"] == "both" else [p["target"]])
        ],
        step("Verificar con el registro de eventos"),
    ],
    _policies,
    backup="Registry.pol se copia a HoneyCheck-datos\\respaldos antes de renombrarlo",
    review=_review,
)

TOOLS = [policies]
