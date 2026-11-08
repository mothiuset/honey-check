"""Controladores: qué falta, qué hay instalado, instalar desde una carpeta, reparar, quitar y
respaldar.

Los paquetes de terceros se leen de %SystemRoot%\\INF\\oem*.inf (Windows guarda ahí una copia de
cada uno al instalarlo) y los aparatos del árbol de dispositivos, con sus identificadores de
hardware: nada depende del texto traducido de pnputil. Instalar desde una carpeta lee cada .inf,
lo cruza con los aparatos de este equipo e instala solo lo que les sirve.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.classification import DEVICE_ERRORS
from honey_check.domain.drivers import (
    DriverMatch,
    InfDriver,
    decode_inf,
    matches,
    needs_driver,
    parse_inf,
)
from honey_check.domain.peripherals import DeviceNode
from honey_check.domain.support import Check, ColumnKind, Risk, Tone, ToolResult
from honey_check.infrastructure.support.base import (
    Params,
    SupportTool,
    check,
    col,
    fact,
    link,
    step,
    table,
    text,
    tool,
)
from honey_check.infrastructure.windows.devnodes import WinDeviceTree

_CATEGORY = "Controladores"
_SYSTEM = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows")
_PNPUTIL = str(_SYSTEM / "System32" / "pnputil.exe")
_OEM = re.compile(r"oem\d{1,5}\.inf", re.IGNORECASE)
_PATH = r"[^\"'\r\n\x00*?<>|]{3,400}"
_INSTANCE = re.compile(r"[A-Za-z0-9_\\&.#{}\-]{3,300}")
_MAX_INFS = 3000
_MAX_INF_BYTES = 8 * 1024 * 1024
# pnputil: 0 hecho; 3010 hecho, falta reiniciar; 259 no había nada mejor que instalar.
_INSTALL_OK = (0, 3010, 259)


def _nodes() -> list[DeviceNode]:
    """Todos los aparatos, también los que no tienen controlador (la simulación lo reemplaza)."""
    return WinDeviceTree().nodes(None)


def _installed_infs() -> list[Path]:
    return sorted((_SYSTEM / "INF").glob("oem*.inf"), key=lambda p: _oem_number(p.name))


def _oem_number(name: str) -> int:
    digits = re.sub(r"\D", "", name)
    return int(digits) if digits else 0


def _read(path: Path) -> InfDriver | None:
    try:
        if path.stat().st_size > _MAX_INF_BYTES:
            return None
        return parse_inf(path.name, decode_inf(path.read_bytes()))
    except OSError:
        return None


def installed_packages() -> list[InfDriver]:
    """Los paquetes de terceros instalados (también los usa Impresoras)."""
    return _installed()


def _installed() -> list[InfDriver]:
    return [driver for path in _installed_infs() if (driver := _read(path))]


def _device_name(node: DeviceNode) -> str:
    return node.name or (node.hardware_ids[0] if node.hardware_ids else node.instance_id)


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


# --- Controladores que faltan ----------------------------------------------------------------------


def _missing(_params: Params, ctx: ToolContext) -> ToolResult:
    ctx.info("Revisando los aparatos conectados")
    nodes = [node for node in _nodes() if node.present]
    lacking = [node for node in nodes if needs_driver(node)]
    in_store = {m.device.instance_id: m for m in matches(_installed(), lacking)}
    checks: list[Check] = []
    for node in lacking:
        found = in_store.get(node.instance_id)
        problem = DEVICE_ERRORS.get(node.problem_code, f"Problema {node.problem_code}")
        if found:
            detail = (
                f"{problem} Windows ya tiene un controlador que le sirve ({found.driver.name}, "
                f"{found.driver.provider or 'sin proveedor'}): repararlo lo vuelve a instalar."
            )
            fix = link("drivers.repair", "Reparar", device=node.instance_id)
        else:
            hwid = node.hardware_ids[0] if node.hardware_ids else node.instance_id
            detail = (
                f"{problem} Busque el controlador del fabricante para «{hwid}» e instálelo "
                "desde su carpeta."
            )
            fix = link("drivers.install", "Instalar desde una carpeta")
        checks.append(check(_device_name(node), False, detail, fix))
    if not lacking:
        checks.append(check("Aparatos conectados", True, "Todos tienen su controlador."))
    return ToolResult(
        summary=[
            fact("Aparatos revisados", len(nodes)),
            fact("Sin controlador o con error", len(lacking), Tone.BAD if lacking else Tone.OK),
        ],
        checks=checks,
        verified=True,
    )


def _missing_state(_params: Params, _env: SupportEnvironment) -> str:
    lacking = sorted(n.instance_id for n in _nodes() if n.present and needs_driver(n))
    return hashlib.sha256("\n".join(lacking).encode()).hexdigest()


missing = SupportTool(
    tool(
        "drivers.missing",
        _CATEGORY,
        "Controladores que faltan",
        "Los aparatos conectados sin controlador o con un error de controlador, y cómo arreglarlo.",
        Risk.READ,
    ),
    lambda _p, _e: [step("Revisar los aparatos conectados", "pnputil /enum-devices /problem")],
    _missing,
    state=_missing_state,
)


# --- Controladores instalados -------------------------------------------------------------------


def _installed_tool(_params: Params, ctx: ToolContext) -> ToolResult:
    ctx.info("Leyendo los paquetes de controladores de terceros")
    drivers = _installed()
    users: dict[str, list[str]] = {}
    for node in _nodes():
        if node.present and node.driver_inf and _OEM.fullmatch(node.driver_inf):
            users.setdefault(node.driver_inf.lower(), []).append(_device_name(node))
    rows = [
        {
            "inf": driver.name,
            "provider": driver.provider,
            "class": driver.driver_class,
            "version": driver.version,
            "date": driver.date.isoformat() if driver.date else None,
            "devices": ", ".join(sorted(set(users.get(driver.name.lower(), []))))
            or "Ninguno ahora",
        }
        for driver in drivers
    ]
    in_use = sum(1 for row in rows if row["devices"] != "Ninguno ahora")
    return ToolResult(
        summary=[
            fact("Paquetes de terceros", len(rows)),
            fact("En uso por un aparato conectado", in_use),
        ],
        checks=[
            check(
                "Respaldo",
                None,
                "Antes de formatear, respalde todos para reinstalarlos después desde su carpeta.",
                link("drivers.backup", "Respaldar todos", inf="*"),
            )
        ],
        tables=[
            table(
                "controladores",
                "Controladores de terceros",
                [
                    col("devices", "Aparatos que lo usan"),
                    col("provider", "Proveedor"),
                    col("class", "Clase", priority=2),
                    col("version", "Versión", priority=2),
                    col("date", "Fecha", ColumnKind.DATE, priority=3),
                    col("inf", "Paquete", priority=3),
                ],
                rows,
                "inf",
                actions=[
                    link("drivers.backup", "Respaldar", inf="{inf}"),
                    link("drivers.repair", "Reparar", inf="{inf}"),
                    link("drivers.remove", "Quitar", Tone.BAD, inf="{inf}"),
                ],
            )
        ],
        verified=True,
    )


def _installed_state(_params: Params, _env: SupportEnvironment) -> str:
    return ",".join(path.name for path in _installed_infs())


installed = SupportTool(
    tool(
        "drivers.installed",
        _CATEGORY,
        "Controladores instalados",
        "Los paquetes de terceros con los aparatos que los usan; respaldar, reparar o quitar.",
        Risk.READ,
    ),
    lambda _p, _e: [step("Leer los paquetes de terceros", "pnputil /enum-drivers")],
    _installed_tool,
    state=_installed_state,
)


# --- Instalar desde una carpeta -------------------------------------------------------------------


def _scan(root: Path) -> list[tuple[Path, InfDriver]]:
    """Los .inf de una carpeta (o un .inf suelto) que declaran algún aparato."""
    paths = [root] if root.suffix.lower() == ".inf" else sorted(root.rglob("*.inf"))[:_MAX_INFS]
    found = []
    for path in paths:
        driver = _read(path)
        if driver and driver.hardware_ids:
            found.append((path, driver))
    return found


def _plan_install(params: Params) -> tuple[list[tuple[Path, InfDriver]], list[DriverMatch]]:
    root = Path(params["path"])
    if not root.exists():
        raise ValueError(f"No existe: {root}")
    found = _scan(root)
    present = [node for node in _nodes() if node.present]
    return found, matches([driver for _, driver in found], present)


def _install_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    try:
        found, useful = _plan_install(params)
    except ValueError as error:
        return "No se puede usar esa carpeta.", [check("Carpeta", False, str(error))], False
    if not found:
        return (
            "La carpeta no tiene controladores (.inf) que declaren aparatos.",
            [check("Carpeta", False, "Elija la carpeta donde se descomprimió el controlador.")],
            False,
        )
    if not useful:
        return (
            f"La carpeta tiene {_plural(len(found), 'controlador', 'controladores')}, pero "
            "ninguno sirve para los aparatos de este equipo.",
            [check("Controladores", False, "No coincide ningún identificador de hardware.")],
            False,
        )
    lacking = [m for m in useful if needs_driver(m.device)]
    checks = [
        check(
            _device_name(m.device),
            True,
            f"{m.driver.name} ({m.driver.provider or 'sin proveedor'}"
            f"{', ' + m.driver.version if m.driver.version else ''})"
            + (" — hoy no tiene controlador" if needs_driver(m.device) else "")
            + (" — compatible, no exacto" if m.rank else ""),
        )
        for m in useful
    ]
    packages = {m.driver.name for m in useful}
    summary = (
        f"De {_plural(len(found), 'controlador', 'controladores')} en la carpeta, "
        f"{_plural(len(packages), 'sirve', 'sirven')} para "
        f"{_plural(len(useful), 'aparato', 'aparatos')} de este equipo"
        + (f" ({len(lacking)} sin controlador ahora)" if lacking else "")
        + ". Se instalan solo esos; Windows deja el mejor para cada aparato."
    )
    return summary, checks, True


def _install(params: Params, ctx: ToolContext) -> ToolResult:
    found, useful = _plan_install(params)
    paths = {driver.name: path for path, driver in found}
    packages = sorted({m.driver.name for m in useful})
    lacking_before = {m.device.instance_id for m in useful if needs_driver(m.device)}
    installed_ok: list[str] = []
    for index, name in enumerate(packages):
        ctx.progress(index, len(packages), f"Instalando {name}")
        output = ctx.command([_PNPUTIL, "/add-driver", str(paths[name]), "/install"], timeout_s=300)
        if output.exit_code in _INSTALL_OK:
            installed_ok.append(name)
        else:
            ctx.warn(f"No se instaló {name} (código {output.exit_code})")
    ctx.progress(len(packages), len(packages), "Buscando aparatos")
    ctx.command([_PNPUTIL, "/scan-devices"], timeout_s=120)
    now = {node.instance_id: node for node in _nodes()}
    checks: list[Check] = []
    for m in useful:
        node = now.get(m.device.instance_id)
        fixed = node is not None and not needs_driver(node)
        if m.device.instance_id in lacking_before:
            checks.append(
                check(
                    _device_name(m.device),
                    fixed,
                    "Ya tiene controlador y funciona." if fixed else "Sigue sin controlador.",
                )
            )
        else:
            checks.append(
                check(_device_name(m.device), True, f"Controlador {m.driver.name} instalado.")
            )
    ok = len(installed_ok) == len(packages) and all(c.status.value != "fail" for c in checks)
    return ToolResult(
        summary=[
            fact("Instalados", f"{len(installed_ok)} de {len(packages)}"),
            fact("Aparatos atendidos", len(useful)),
        ],
        checks=checks,
        verified=ok,
    )


install = SupportTool(
    tool(
        "drivers.install",
        _CATEGORY,
        "Instalar controladores desde una carpeta",
        "Lee los controladores de una carpeta (o un .inf), los cruza con los aparatos de este "
        "equipo e instala los que les sirven.",
        Risk.CHANGE,
        params=[
            text(
                "path",
                "Carpeta o archivo .inf",
                required=True,
                pattern=_PATH,
                help=r"Por ejemplo D:\Controladores o una USB con los del fabricante",
                browse="folder",
            )
        ],
        admin=True,
        action="Instalar",
    ),
    lambda p, _e: [
        step(
            "Leer los .inf de la carpeta y cruzarlos con los aparatos",
            f'dir /s "{p["path"]}\\*.inf"',
        ),
        step("Instalar los que sirven", 'pnputil /add-driver "<archivo.inf>" /install'),
        step("Buscar aparatos de nuevo", "pnputil /scan-devices"),
    ],
    _install,
    review=_install_review,
)


# --- Reparar ----------------------------------------------------------------------------------------


def _targets(params: Params) -> list[DeviceNode]:
    nodes = [node for node in _nodes() if node.present]
    device = params.get("device")
    if device:
        return [n for n in nodes if n.instance_id.upper() == str(device).upper()]
    inf = str(params.get("inf") or "").lower()
    return [n for n in nodes if (n.driver_inf or "").lower() == inf]


def _repair_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    targets = _targets(params)
    if not targets:
        return (
            "No hay aparatos conectados con ese controlador.",
            [check("Aparatos", None, "Nada que reparar.")],
            False,
        )
    checks = [
        check(_device_name(n), True, "Se quita del aparato y Windows lo reinstala.")
        for n in targets
    ]
    return (
        f"Se reinstalará el controlador de {_plural(len(targets), 'aparato', 'aparatos')}: Windows "
        "lo quita del aparato y lo vuelve a instalar. El aparato deja de funcionar unos segundos.",
        checks,
        True,
    )


def _repair(params: Params, ctx: ToolContext) -> ToolResult:
    targets = _targets(params)
    for node in targets:
        ctx.info(f"Reinstalando {_device_name(node)}")
        ctx.command([_PNPUTIL, "/remove-device", node.instance_id], timeout_s=60)
    ctx.command([_PNPUTIL, "/scan-devices"], timeout_s=120)
    now = {node.instance_id.upper(): node for node in _nodes()}
    checks = []
    for node in targets:
        again = now.get(node.instance_id.upper())
        ok = again is not None and again.present and not needs_driver(again)
        checks.append(
            check(
                _device_name(node),
                ok,
                "Reinstalado y funcionando."
                if ok
                else "Windows no lo volvió a instalar: desconéctelo y conéctelo, o reinicie.",
            )
        )
    return ToolResult(
        summary=[fact("Reparados", sum(c.status.value == "ok" for c in checks))],
        checks=checks,
        verified=all(c.status.value == "ok" for c in checks),
    )


repair = SupportTool(
    tool(
        "drivers.repair",
        _CATEGORY,
        "Reparar un controlador",
        "Quita el controlador de un aparato y deja que Windows lo reinstale.",
        Risk.CHANGE,
        params=[
            text("device", "Aparato", pattern=_INSTANCE.pattern),
            text("inf", "Paquete", pattern=_OEM.pattern),
        ],
        admin=True,
        hidden=True,
        action="Reparar",
    ),
    lambda _p, _e: [
        step(
            "Quitar el aparato para que Windows lo vuelva a reconocer",
            "pnputil /remove-device <id>",
        ),
        step("Buscar aparatos de nuevo", "pnputil /scan-devices"),
    ],
    _repair,
    review=_repair_review,
)


# --- Respaldar ------------------------------------------------------------------------------------


def _backup_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    inf = params["inf"]
    if inf == "*":
        count = len(_installed_infs())
        return (
            f"Se copiarán los {count} paquetes de terceros a HoneyCheck-datos\\salidas. Para "
            "reinstalarlos: «Instalar controladores desde una carpeta» con esa carpeta.",
            [],
            True,
        )
    return f"Se copiará {inf} a HoneyCheck-datos\\salidas.", [], True


def _backup(params: Params, ctx: ToolContext) -> ToolResult:
    folder = ctx.output_path("controladores")
    folder.mkdir(parents=True, exist_ok=True)
    inf = params["inf"]
    output = ctx.command([_PNPUTIL, "/export-driver", inf, str(folder)], timeout_s=900)
    saved = len(list(folder.rglob("*.inf")))
    ok = output.exit_code == 0 and saved > 0
    return ToolResult(
        summary=[fact("Paquetes copiados", saved), fact("Carpeta", str(folder))],
        checks=[
            check(
                "Respaldo",
                ok,
                f"En {folder}." if ok else f"pnputil terminó con el código {output.exit_code}.",
                link("explorer.open", "Abrir la carpeta", path=str(folder)) if ok else None,
            )
        ],
        verified=ok,
    )


backup = SupportTool(
    tool(
        "drivers.backup",
        _CATEGORY,
        "Respaldar controladores",
        "Copia los controladores de terceros (todos o uno) a una carpeta para reinstalarlos.",
        Risk.CHANGE,
        params=[
            text(
                "inf",
                "Paquete",
                required=True,
                default="*",
                pattern=r"\*|" + _OEM.pattern,
                help="«*» para todos, o el paquete (oem12.inf)",
            )
        ],
        admin=True,
        action="Respaldar",
    ),
    lambda p, _e: [step("Copiar los paquetes", f'pnputil /export-driver {p["inf"]} "<carpeta>"')],
    _backup,
    review=_backup_review,
)


# --- Quitar ----------------------------------------------------------------------------------------


def _remove_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    inf = params["inf"]
    if not (_SYSTEM / "INF" / inf).exists():
        return f"{inf} no está instalado.", [check(inf, None, "Nada que quitar.")], False
    users = [n for n in _nodes() if n.present and (n.driver_inf or "").lower() == inf.lower()]
    checks = [
        check(
            _device_name(n),
            False,
            "Lo usa ahora: quedará con el controlador genérico de Windows o sin controlador.",
            warn=True,
        )
        for n in users
    ]
    return (
        f"Se quitará el paquete {inf} de Windows, con respaldo previo para poder reinstalarlo.",
        checks,
        True,
    )


def _remove(params: Params, ctx: ToolContext) -> ToolResult:
    inf = params["inf"]
    folder = ctx.backup_path(f"controlador {inf}")
    folder.mkdir(parents=True, exist_ok=True)
    ctx.command([_PNPUTIL, "/export-driver", inf, str(folder)], timeout_s=300)
    saved = any(folder.rglob("*.inf"))
    if not saved:
        ctx.warn("No se pudo respaldar el paquete: no se quita.")
        return ToolResult(
            checks=[check(inf, False, "Sin respaldo no se quita.")],
            verified=False,
        )
    output = ctx.command([_PNPUTIL, "/delete-driver", inf, "/uninstall"], timeout_s=300)
    gone = not (_SYSTEM / "INF" / inf).exists()
    return ToolResult(
        summary=[fact("Quitado", inf if gone else "No"), fact("Respaldo", str(folder))],
        checks=[
            check(
                inf,
                gone,
                "Quitado de Windows."
                if gone
                else f"Sigue instalado (código {output.exit_code}): un aparato lo está usando.",
            ),
            check(
                "Respaldo",
                True,
                f"En {folder}.",
                link("drivers.install", "Reinstalar", path=str(folder)),
            ),
        ],
        verified=gone,
    )


remove = SupportTool(
    tool(
        "drivers.remove",
        _CATEGORY,
        "Quitar un controlador",
        "Quita un paquete de controlador de terceros, con respaldo previo.",
        Risk.DESTRUCTIVE,
        params=[text("inf", "Paquete", required=True, pattern=_OEM.pattern)],
        admin=True,
        hidden=True,
        action="Quitar",
    ),
    lambda p, _e: [
        step("Respaldar el paquete", f'pnputil /export-driver {p["inf"]} "<respaldo>"'),
        step(
            "Quitarlo de Windows y de sus aparatos", f"pnputil /delete-driver {p['inf']} /uninstall"
        ),
    ],
    _remove,
    review=_remove_review,
    backup="Copia del paquete en HoneyCheck-datos\\respaldos",
)

TOOLS = [missing, installed, install, repair, backup, remove]
