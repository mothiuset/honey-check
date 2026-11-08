"""Aparatos que Windows recuerda sin estar conectados.

- **Quitar restos**: lo que se conectó alguna vez y ya no está (un receptor en otro puerto, una
  memoria USB, un teléfono). Antes de quitar se respalda la lista de sus partes y sus
  controladores de terceros; nunca se quita algo conectado. Windows lo vuelve a crear si el aparato
  se conecta de nuevo.
- **Restaurar**: reinstala los controladores respaldados y vuelve a buscar aparatos.
- **Olvidar un Bluetooth**: desempareja (como «Quitar dispositivo» en Configuración).

Se trabaja sobre el árbol de dispositivos en vivo: el inventario puede ser de hace días.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.peripherals import (
    PERIPHERAL_CLASSES,
    DeviceGroup,
    group_devices,
    parse_instance_id,
)
from honey_check.domain.support import Check, Risk, ToolResult
from honey_check.infrastructure.support.base import (
    Params,
    SupportTool,
    check,
    fact,
    link,
    multi,
    step,
    text,
    tool,
)
from honey_check.infrastructure.windows import bluetooth
from honey_check.infrastructure.windows.devnodes import WinDeviceTree, is_present, uninstall

_CATEGORY = "Periféricos"
_INSTANCE = re.compile(r"[A-Za-z0-9_\\&.#{}\-]{3,300}")
_PNPUTIL = str(Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "pnputil.exe")
_BACKUP = re.compile(r"[^\"'\r\n\x00]{3,400}")
_INDEX = "dispositivos.json"


def _live() -> list[DeviceGroup]:
    """Los aparatos tal como están ahora (la simulación de las pruebas reemplaza esta función)."""
    return group_devices(WinDeviceTree().nodes(PERIPHERAL_CLASSES))


def _named(group: DeviceGroup) -> str:
    return group.name or "Aparato sin nombre"


def _requested(params: Params) -> tuple[list[DeviceGroup], list[str]]:
    """Los aparatos pedidos (por cualquiera de sus partes) y las partes que Windows ya olvidó."""
    wanted = [item for item in params["devices"] if _INSTANCE.fullmatch(item)]
    groups = _live()
    found: list[DeviceGroup] = []
    missing: list[str] = []
    for instance in wanted:
        group = next(
            (
                g
                for g in groups
                if instance.upper() in {node.instance_id.upper() for node in g.members}
            ),
            None,
        )
        if group is None:
            missing.append(instance)
        elif group not in found:
            found.append(group)
    return found, missing


def _parts_phrase(count: int) -> str:
    return f"{count} parte{'s' if count != 1 else ''}"


# --- Quitar restos -------------------------------------------------------------------------------


def _remove_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    groups, missing = _requested(params)
    checks: list[Check] = []
    removable = 0
    for group in groups:
        if group.present:
            checks.append(check(_named(group), False, "Está conectado ahora: no se quita."))
        elif group.is_bluetooth_device:
            checks.append(
                check(
                    _named(group),
                    False,
                    "Está emparejado por Bluetooth: use «Olvidar» para desemparejarlo.",
                )
            )
        else:
            removable += 1
            drivers = ", ".join(group.driver_infs)
            detail = f"{_parts_phrase(len(group.members))}; " + (
                f"se respalda su controlador ({drivers})."
                if drivers
                else "su controlador es de Windows y sigue disponible."
            )
            checks.append(check(_named(group), True, detail))
    checks += [check(item, None, "Windows ya no lo recuerda.") for item in missing]
    if not removable:
        return "No hay nada que quitar: lo elegido está conectado o ya no existe.", checks, False
    noun = "aparato" if removable == 1 else "aparatos"
    summary = (
        f"Se quitará{'n' if removable != 1 else ''} {removable} {noun} que ya no "
        "está conectado. Si lo vuelve a conectar, Windows lo reconoce solo."
        if removable == 1
        else f"Se quitarán {removable} {noun} que ya no están conectados. Si vuelve a conectar "
        "alguno, Windows lo reconoce solo."
    )
    return summary, checks, True


def _order(group: DeviceGroup) -> list[str]:
    """Partes de abajo hacia arriba: primero las que cuelgan de otras."""
    ids = {node.instance_id.upper(): node for node in group.members}

    def depth(instance: str) -> int:
        level = 0
        node = ids.get(instance)
        while node is not None and (node.parent or "").upper() in ids and level < 20:
            level += 1
            node = ids[(node.parent or "").upper()]
        return level

    return sorted((node.instance_id for node in group.members), key=lambda i: -depth(i.upper()))


def _backup(ctx: ToolContext, groups: list[DeviceGroup]) -> tuple[Path, list[str]]:
    folder = ctx.backup_path("dispositivos")
    folder.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for inf in sorted({inf for group in groups for inf in group.driver_infs}):
        target = folder / "controladores" / Path(inf).stem
        target.mkdir(parents=True, exist_ok=True)
        output = ctx.command([_PNPUTIL, "/export-driver", inf, str(target)], timeout_s=120)
        if output.exit_code == 0 and any(target.glob("*.inf")):
            saved.append(inf)
        else:
            ctx.warn(f"No se pudo respaldar {inf}; sigue instalado en Windows.")
    index = [
        {
            "name": _named(group),
            "functions": [f.value for f in group.functions],
            "connection": group.connection.value,
            "vendorId": group.hardware.vendor_id,
            "productId": group.hardware.product_id,
            "drivers": [inf for inf in group.driver_infs if inf in saved],
            "parts": [
                {"instanceId": node.instance_id, "name": node.name, "class": node.pnp_class}
                for node in group.members
            ],
        }
        for group in groups
    ]
    document = {"savedAt": datetime.now(UTC).isoformat(), "devices": index}
    (folder / _INDEX).write_text(json.dumps(document, indent=2, ensure_ascii=False), "utf-8")
    return folder, saved


def _remove_part(ctx: ToolContext, instance: str) -> bool:
    if is_present(instance):
        ctx.warn(f"{instance} está conectado ahora: no se quita.")
        return False
    return (
        first_that_works(
            ctx,
            [
                Attempt(
                    "pnputil /remove-device",
                    lambda: (
                        ctx.command([_PNPUTIL, "/remove-device", instance], timeout_s=60).exit_code
                        == 0
                        and is_present(instance) is None
                    ),
                ),
                Attempt(
                    "API CM_Uninstall_DevNode",
                    lambda: uninstall(instance) == 0 and is_present(instance) is None,
                ),
            ],
        )
        is not None
    )


def _remove(params: Params, ctx: ToolContext) -> ToolResult:
    groups, _missing = _requested(params)
    groups = [g for g in groups if not g.present and not g.is_bluetooth_device]
    if not groups:
        return ToolResult(summary=[fact("Quitados", 0)], verified=True)
    ctx.info("Respaldando la lista de partes y los controladores")
    folder, saved = _backup(ctx, groups)
    checks: list[Check] = []
    removed = 0
    for index, group in enumerate(groups):
        ctx.progress(index, len(groups), f"Quitando {_named(group)}")
        parts = _order(group)
        done = [instance for instance in parts if _remove_part(ctx, instance)]
        ok = len(done) == len(parts)
        removed += ok
        checks.append(
            check(
                _named(group),
                ok,
                f"Quitado ({_parts_phrase(len(parts))})."
                if ok
                else f"Se quitaron {len(done)} de {len(parts)} partes; lo que queda sigue igual.",
            )
        )
    ctx.progress(len(groups), len(groups))
    checks.append(
        check(
            "Respaldo",
            True,
            f"Lista de partes y {len(saved)} controlador{'es' if len(saved) != 1 else ''} "
            f"en {folder}.",
            link("devices.restore", "Restaurar", backup=str(folder)),
        )
    )
    return ToolResult(
        summary=[fact("Quitados", f"{removed} de {len(groups)}"), fact("Respaldo", str(folder))],
        checks=checks,
        verified=removed == len(groups),
    )


remove_leftovers = SupportTool(
    tool(
        "devices.remove_leftovers",
        _CATEGORY,
        "Quitar aparatos que ya no están",
        "Quita de Windows aparatos que se conectaron alguna vez y ya no están, con respaldo.",
        Risk.DESTRUCTIVE,
        params=[multi("devices", "Aparatos")],
        admin=True,
        hidden=True,
        action="Quitar",
    ),
    lambda p, _e: [
        step("Respaldar la lista de partes y los controladores", "pnputil /export-driver oem*.inf"),
        *[step(f"Quitar {item}", f'pnputil /remove-device "{item}"') for item in p["devices"]],
    ],
    _remove,
    review=_remove_review,
    backup="Lista de partes y controladores de terceros en HoneyCheck-datos\\respaldos",
)


# --- Restaurar -----------------------------------------------------------------------------------


def _read_backup(params: Params) -> tuple[Path, list[dict[str, Any]]]:
    folder = Path(params["backup"])
    data = json.loads((folder / _INDEX).read_text(encoding="utf-8"))
    devices = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list):
        raise ValueError("El respaldo no tiene la lista de aparatos")
    return folder, [item for item in devices if isinstance(item, dict)]


def _restore_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    try:
        folder, devices = _read_backup(params)
    except (OSError, ValueError) as error:
        detail = "No se encontró." if isinstance(error, OSError) else str(error)
        return "No se puede usar ese respaldo.", [check("Respaldo", False, detail)], False
    drivers = list((folder / "controladores").glob("*/*.inf"))
    checks = [
        check(
            str(item.get("name") or "Aparato"),
            True,
            "Se reinstala su controlador."
            if item.get("drivers")
            else "Su controlador es de Windows.",
        )
        for item in devices
    ]
    summary = (
        f"Se reinstalarán {len(drivers)} controlador{'es' if len(drivers) != 1 else ''} y Windows "
        "volverá a buscar aparatos. Lo que esté conectado aparece al momento; el resto, al "
        "conectarlo."
    )
    return summary, checks, bool(drivers)


def _restore(params: Params, ctx: ToolContext) -> ToolResult:
    folder, devices = _read_backup(params)
    installed = 0
    drivers = sorted((folder / "controladores").glob("*/*.inf"))
    for inf in drivers:
        output = ctx.command([_PNPUTIL, "/add-driver", str(inf), "/install"], timeout_s=180)
        installed += output.exit_code in (0, 3010)  # 3010: hace falta reiniciar
    ctx.command([_PNPUTIL, "/scan-devices"], timeout_s=120)
    checks: list[Check] = []
    for item in devices:
        parts = [
            str(part.get("instanceId"))
            for part in item.get("parts", [])
            if isinstance(part, dict) and part.get("instanceId")
        ]
        back = any(is_present(instance) for instance in parts)
        checks.append(
            check(
                str(item.get("name") or "Aparato"),
                True if back else None,
                "Conectado y reconocido." if back else "Se reconocerá al conectarlo.",
            )
        )
    ok = installed == len(drivers)
    checks.insert(
        0,
        check(
            "Controladores",
            ok,
            f"{installed} de {len(drivers)} reinstalados."
            if drivers
            else "No había controladores de terceros que reinstalar.",
        ),
    )
    return ToolResult(
        summary=[fact("Controladores", f"{installed} de {len(drivers)}")],
        checks=checks,
        verified=ok,
    )


restore = SupportTool(
    tool(
        "devices.restore",
        _CATEGORY,
        "Restaurar aparatos quitados",
        "Reinstala los controladores de un respaldo y vuelve a buscar aparatos.",
        Risk.CHANGE,
        params=[text("backup", "Respaldo", required=True, pattern=_BACKUP.pattern)],
        admin=True,
        hidden=True,
        action="Restaurar",
    ),
    lambda p, _e: [
        step(
            "Reinstalar los controladores respaldados",
            f'pnputil /add-driver "{p["backup"]}\\controladores\\*\\*.inf" /install',
        ),
        step("Volver a buscar aparatos", "pnputil /scan-devices"),
    ],
    _restore,
    review=_restore_review,
)


# --- Olvidar un Bluetooth --------------------------------------------------------------------------


def _address(group: DeviceGroup) -> str | None:
    return next(
        (
            parse_instance_id(node.instance_id).serial
            for node in group.members
            if re.match(r"^(BTHENUM|BTHLE)\\DEV_", node.instance_id, re.IGNORECASE)
        ),
        None,
    )


def _forget_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    groups, missing = _requested(params)
    paired = [g for g in groups if g.is_bluetooth_device and _address(g)]
    checks = [
        check(
            _named(group),
            True,
            "Está conectado ahora: se desconectará."
            if group.present
            else "Emparejado, no conectado.",
            warn=group.present,
        )
        for group in paired
    ]
    checks += [check(item, None, "Windows ya no lo recuerda.") for item in missing]
    if not paired:
        return "No hay nada que olvidar.", checks, False
    summary = (
        f"Windows olvidará {len(paired)} aparato{'s' if len(paired) != 1 else ''} Bluetooth. "
        "Un emparejamiento no se puede respaldar: para volver a usarlo, emparéjelo otra vez "
        "desde Configuración."
    )
    return summary, checks, False


def _forget(params: Params, ctx: ToolContext) -> ToolResult:
    groups, _missing = _requested(params)
    checks: list[Check] = []
    done = 0
    for group in groups:
        mac = _address(group)
        if not group.is_bluetooth_device or not mac:
            continue
        code = bluetooth.forget(mac)
        root = group.root.instance_id
        gone = False
        for _ in range(20):  # Windows quita sus nodos en unos segundos
            if is_present(root) is None:
                gone = True
                break
            time.sleep(0.25)
        done += gone
        checks.append(
            check(
                _named(group),
                gone,
                "Olvidado." if gone else f"Windows no lo olvidó (código {code}).",
            )
        )
    return ToolResult(
        summary=[fact("Olvidados", done)], checks=checks, verified=done == len(checks)
    )


forget = SupportTool(
    tool(
        "bluetooth.forget",
        _CATEGORY,
        "Olvidar un aparato Bluetooth",
        "Desempareja un aparato Bluetooth, como «Quitar dispositivo» en Configuración.",
        Risk.CHANGE,
        params=[multi("devices", "Aparatos")],
        hidden=True,
        action="Olvidar",
    ),
    lambda p, _e: [step(f"Olvidar {item}", "BluetoothRemoveDevice") for item in p["devices"]],
    _forget,
    review=_forget_review,
)

TOOLS = [remove_leftovers, restore, forget]
