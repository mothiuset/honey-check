"""Programas: desinstalar (normal, con asistente o forzado), buscar restos con evidencia y
eliminarlos insistiendo por vías distintas, siempre con respaldo.

El modo forzado es el desinstalador propio de Honey Check: cierra el programa y sus servicios,
intenta el desinstalador oficial con un límite de tiempo, quita el registro de Windows Installer
si quedó huérfano y elimina todo lo que encuentre (carpetas, accesos directos, Registro, inicio
automático, servicios, tareas programadas y reglas del firewall). Cada eliminación deja respaldo:
las carpetas van a la Papelera y lo demás se exporta antes de borrarlo.
"""

from __future__ import annotations

import json
import os
import re
import winreg
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from honey_check.application.ports import CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import SupportEnvironment, ToolContext, UserSession
from honey_check.domain.inventory import DetectionMechanism, SoftwareItem
from honey_check.domain.support import (
    Check,
    CheckStatus,
    ColumnKind,
    FileRef,
    PlanStep,
    Risk,
    Tone,
    ToolResult,
)
from honey_check.infrastructure.windows.errors import Failure, installer_exit
from honey_check.infrastructure.windows.locks import (
    close_processes_using,
    processes_using,
    running_from,
)
from honey_check.infrastructure.windows.session import user_registry_key

from .. import removal
from ..base import (
    Params,
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
from ..filesystem import folder_size, is_folder
from ..runner import tool_path
from ..winops import SC, powershell, split_command_line, stop_service, wmi_rows
from .disk import protected
from .registry import delete as registry_delete

MSIEXEC = tool_path("msiexec.exe")
SCHTASKS = tool_path("schtasks.exe")
_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
PRODUCT_CODE = re.compile(r"^\{[0-9A-Fa-f-]{36}\}$")
_ID = r"[0-9a-f]{16}"
_OK_EXIT = (0, 1605, 1641, 3010)
_FORCED_UNINSTALLER_TIMEOUT_S = 600.0

KINDS = {
    "folder": "Carpeta",
    "file": "Acceso directo",
    "key": "Registro",
    "value": "Inicio automático",
    "service": "Servicio",
    "task": "Tarea programada",
    "firewall": "Regla del firewall",
}


# Singular y plural para contar restos en una frase.
_NOUNS = {
    "folder": ("carpeta", "carpetas"),
    "file": ("acceso directo", "accesos directos"),
    "key": ("clave del Registro", "claves del Registro"),
    "value": ("inicio automático", "inicios automáticos"),
    "service": ("servicio", "servicios"),
    "task": ("tarea programada", "tareas programadas"),
    "firewall": ("regla del firewall", "reglas del firewall"),
}
_BACKUP_NOTE = {
    "key": "Se exporta a .reg antes de borrarla",
    "value": "Se exporta a .reg antes de borrarlo",
    "service": "Se detiene y se exporta a .reg antes de borrarlo",
    "task": "Se guarda su XML antes de borrarla",
    "firewall": "Se guarda su definición antes de borrarla",
}


def count_phrase(kinds: list[str]) -> str:
    """«2 carpetas y 1 clave del Registro»."""
    counts: dict[str, int] = {}
    for kind in kinds:
        counts[kind] = counts.get(kind, 0) + 1
    parts = [
        f"{n} {_NOUNS.get(kind, (kind, kind))[0 if n == 1 else 1]}" for kind, n in counts.items()
    ]
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} y {parts[-1]}"


# --- Localizar el programa ---------------------------------------------------------------------------


def find_item(env: SupportEnvironment, software_id: str) -> SoftwareItem:
    inventory = env.inventory
    if inventory is None or inventory.software is None:
        raise ValueError("Primero analice el equipo: el programa se toma del último inventario")
    item = next((i for i in inventory.software.items if i.id == software_id), None)
    if item is None:
        raise ValueError("El programa no está en el último inventario de este equipo")
    return item


def _registry_location(item: SoftwareItem) -> tuple[str, int, str] | None:
    """Colmena corta, vista y clave de desinstalación (desde su origen en el inventario)."""
    match = re.match(r"^registry:(HKLM\\64|HKLM\\32|HKCU)\\(.+)$", item.detection_source)
    if not match:
        return None
    label, key = match.groups()
    view = winreg.KEY_WOW64_32KEY if label == "HKLM\\32" else winreg.KEY_WOW64_64KEY
    return ("HKCU" if label == "HKCU" else "HKLM"), view, key


def _open(short: str, view: int, session: UserSession | None) -> winreg.HKEYType:
    """Abre una clave en lectura; HKCU es la del usuario de la sesión aunque el proceso no lo sea."""
    resolved = user_registry_key(short, session)
    head, _, sub = resolved.partition("\\")
    hive = {
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKU": winreg.HKEY_USERS,
    }[head]
    return winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | view)


def _uninstall_values(item: SoftwareItem, session: UserSession | None) -> dict[str, object] | None:
    location = _registry_location(item)
    if location is None:
        return None
    hive, view, key = location
    try:
        with _open(f"{hive}\\{_UNINSTALL}\\{key}", view, session) as handle:
            values: dict[str, object] = {}
            index = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(handle, index)
                except OSError:
                    break
                values[name] = data
                index += 1
            values["__key__"] = key
            return values
    except OSError:
        return None


_UNINSTALL_ROOTS = (
    ("HKLM", winreg.KEY_WOW64_64KEY, "HKLM\\64"),
    ("HKLM", winreg.KEY_WOW64_32KEY, "HKLM\\32"),
    ("HKCU", winreg.KEY_WOW64_64KEY, "HKCU"),
)


def uninstall_entries(session: UserSession | None) -> dict[str, str]:
    """Programas registrados ahora: origen como en el inventario («registry:HKLM\\64\\clave») →
    nombre. Solo los que tienen nombre y no son componentes del sistema."""
    found: dict[str, str] = {}
    for hive, view, label in _UNINSTALL_ROOTS:
        try:
            root = _open(f"{hive}\\{_UNINSTALL}", view, session)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    key = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, key) as entry:
                        name = str(winreg.QueryValueEx(entry, "DisplayName")[0])
                        try:
                            hidden = int(winreg.QueryValueEx(entry, "SystemComponent")[0]) == 1
                        except OSError:
                            hidden = False
                except OSError:
                    continue
                if name and not hidden:
                    found[f"registry:{label}\\{key}"] = name
    return found


def still_installed(item: SoftwareItem, session: UserSession | None) -> bool:
    """Si el programa sigue instalado ahora (un paquete AppX, si su carpeta sigue ahí)."""
    if item.mechanism is DetectionMechanism.APPX_PACKAGE:
        folder = item.install_path.value
        return bool(folder) and Path(str(folder)).is_dir()
    return _uninstall_values(item, session) is not None


def _commands(
    item: SoftwareItem, quiet: bool, session: UserSession | None
) -> list[tuple[str, list[str]]]:
    """Vías de desinstalación en orden de preferencia."""
    values = _uninstall_values(item, session) or {}
    ways: list[tuple[str, list[str]]] = []
    key = str(values.get("__key__") or "")
    if (values.get("WindowsInstaller") == 1 or PRODUCT_CODE.match(key)) and PRODUCT_CODE.match(key):
        ways.append(
            (
                f"msiexec /x {key}",
                [MSIEXEC, "/x", key, "/qn" if quiet else "/qb", "/norestart"],
            )
        )
    if quiet and isinstance(values.get("QuietUninstallString"), str):
        ways.append(
            (
                "Desinstalación silenciosa registrada",
                split_command_line(str(values["QuietUninstallString"])),
            )
        )
    if isinstance(values.get("UninstallString"), str):
        ways.append(
            (
                "Desinstalador oficial del programa",
                split_command_line(str(values["UninstallString"])),
            )
        )
    return [(label, args) for label, args in ways if args]


def _still_installed(item: SoftwareItem, session: UserSession | None) -> bool:
    if item.mechanism is DetectionMechanism.APPX_PACKAGE:
        return False  # se comprueba aparte con Get-AppxPackage
    return _uninstall_values(item, session) is not None


def _install_folder(item: SoftwareItem) -> Path | None:
    install = item.install_path.value
    if install and is_folder(Path(install)):
        return Path(install)
    return None


# --- Restos ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Leftover:
    kind: str
    target: str  # ruta, clave, «clave|valor», servicio, tarea o regla
    evidence: str
    size: int | None = None

    @property
    def id(self) -> str:
        return f"{self.kind}|{self.target}"

    def row(self) -> dict[str, object]:
        shown = self.target.replace("|", " → ") if self.kind == "value" else self.target
        return {
            "id": self.id,
            "kind": KINDS.get(self.kind, self.kind),
            "path": shown,
            "size": self.size,
            "evidence": self.evidence,
        }


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


_SUFFIX = re.compile(r"[\s(\[-]*(v?\d+(\.\d+)*|x64|x86|64-bit|32-bit)[)\]]*\s*$", re.I)


def base_name(name: str) -> str:
    """«Programa Ficticio 2.3 (x64)» → «Programa Ficticio»: quita versiones y arquitectura."""
    current = name.strip()
    while (shorter := _SUFFIX.sub("", current).strip()) and shorter != current:
        current = shorter
    return current or name


def _roots(session: UserSession | None) -> tuple[list[Path], list[Path]]:
    """Carpetas donde los programas guardan datos y donde dejan accesos directos."""
    appdata = session.appdata if session else os.environ.get("APPDATA", "")
    local = session.local_appdata if session else os.environ.get("LOCALAPPDATA", "")
    desktop = session.desktop if session else ""
    program_data = os.environ.get("PROGRAMDATA", "")
    data = [
        Path(os.environ.get("PROGRAMFILES", "")),
        Path(os.environ.get("PROGRAMFILES(X86)", "")),
        Path(program_data),
        Path(appdata),
        Path(local),
        Path(local) / "Programs",  # instalaciones por usuario (Electron, Squirrel…)
    ]
    shortcuts = [
        Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
        *([Path(desktop)] if desktop else []),
    ]
    return [p for p in data if str(p) not in ("", ".")], [
        p for p in shortcuts if str(p) not in ("", ".")
    ]


def _folders(item: SoftwareItem, env: SupportEnvironment) -> list[tuple[Path, str]]:
    names = {base_name(item.name), item.name}
    publisher = item.publisher.value
    target = _normalized(base_name(item.name))
    found: list[tuple[Path, str]] = []
    install = _install_folder(item)
    if install:
        found.append((install, "Carpeta de instalación registrada"))
    data_roots, shortcut_roots = _roots(env.user)
    for root in [*data_roots, *shortcut_roots[:2]]:
        if not is_folder(root):
            continue
        for name in names:
            found.append((root / name, "Lleva el nombre del programa"))
            if publisher:
                found.append((root / publisher / name, "Editor y nombre del programa"))
        if publisher and is_folder(root / publisher):
            others = [
                f for f in (root / publisher).iterdir() if _normalized(f.name) not in ("", target)
            ]
            # La carpeta del editor solo se propone si no guarda otros programas suyos.
            if not others:
                found.append((root / publisher, "Carpeta del editor, sin otros programas"))
    return [(p, why) for p, why in found if is_folder(p) and protected(p, env) is None]


def _shortcuts(item: SoftwareItem, env: SupportEnvironment) -> list[Path]:
    target = _normalized(base_name(item.name))
    if len(target) < 3:
        return []
    found = []
    for root in _roots(env.user)[1]:
        if not is_folder(root):
            continue
        for path in root.glob("*.lnk"):
            if target in _normalized(path.stem):
                found.append(path)
    return found


def _registry_keys(item: SoftwareItem, session: UserSession | None) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    location = _registry_location(item)
    if location and _uninstall_values(item, session) is not None:
        hive, view, key = location
        root = "SOFTWARE\\WOW6432Node" if view == winreg.KEY_WOW64_32KEY else "SOFTWARE"
        keys.append(
            (
                f"{hive}\\{root}\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{key}",
                "Entrada de desinstalación de Windows",
            )
        )
    subs = [base_name(item.name)]
    if item.publisher.value:
        subs.insert(0, f"{item.publisher.value}\\{base_name(item.name)}")
    for hive in ("HKCU", "HKLM"):
        for software_root in ("SOFTWARE", "SOFTWARE\\WOW6432Node"):
            for sub in subs:
                short = f"{hive}\\{software_root}\\{sub}"
                try:
                    with _open(short, winreg.KEY_WOW64_64KEY, session):
                        keys.append((short, "Configuración del programa"))
                except OSError:
                    continue
    return keys


def packed_guid(code: str) -> str:
    """Código de producto MSI en la forma comprimida de Windows Installer (Installer\\Products)."""
    raw = code.strip("{}").replace("-", "").upper()
    head = raw[:8][::-1] + raw[8:12][::-1] + raw[12:16][::-1]
    tail = "".join(raw[i : i + 2][::-1] for i in range(16, 32, 2))
    return head + tail


def _installer_keys(item: SoftwareItem, session: UserSession | None) -> list[tuple[str, str]]:
    """Registro de Windows Installer: si el desinstalador falló, deja el producto «instalado»."""
    location = _registry_location(item)
    if location is None or not PRODUCT_CODE.match(location[2]):
        return []
    packed = packed_guid(location[2])
    candidates = [
        f"HKLM\\SOFTWARE\\Classes\\Installer\\Products\\{packed}",
        f"HKLM\\SOFTWARE\\Classes\\Installer\\Features\\{packed}",
        "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Installer\\UserData\\S-1-5-18"
        f"\\Products\\{packed}",
        f"HKCU\\SOFTWARE\\Microsoft\\Installer\\Products\\{packed}",
        f"HKCU\\SOFTWARE\\Microsoft\\Installer\\Features\\{packed}",
    ]
    if session:
        candidates.append(
            "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Installer\\UserData\\"
            f"{session.sid}\\Products\\{packed}"
        )
    found = []
    for short in candidates:
        try:
            with _open(short, winreg.KEY_WOW64_64KEY, session):
                found.append((short, "Registro de Windows Installer"))
        except OSError:
            continue
    return found


def _run_entries(
    item: SoftwareItem, install: Path | None, session: UserSession | None
) -> list[tuple[str, str]]:
    target = _normalized(base_name(item.name))
    needle = str(install).lower() if install else None
    found = []
    for hive in ("HKCU", "HKLM"):
        for root in ("SOFTWARE", "SOFTWARE\\WOW6432Node"):
            short = f"{hive}\\{root}\\Microsoft\\Windows\\CurrentVersion\\Run"
            try:
                with _open(short, winreg.KEY_WOW64_64KEY, session) as key:
                    index = 0
                    while True:
                        try:
                            name, data, _ = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        command = str(data).lower()
                        if (needle and needle in command) or (
                            len(target) >= 4 and target in _normalized(name)
                        ):
                            found.append((f"{short}|{name}", f"Arranca con Windows: {data}"))
            except OSError:
                continue
    return found


_TASKS_AND_RULES = r"""
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$out = @{ tasks = @(); rules = @() }
try {
  foreach ($t in Get-ScheduledTask -ErrorAction Stop) {
    $exe = ($t.Actions | Where-Object { $_.Execute } | Select-Object -First 1).Execute
    $out.tasks += @{ path = "$($t.TaskPath)$($t.TaskName)"; name = $t.TaskName; exe = "$exe" }
  }
} catch {}
if ($in.install) {
  try {
    $like = "$($in.install)*"
    foreach ($f in Get-NetFirewallApplicationFilter -ErrorAction Stop |
             Where-Object { $_.Program -like $like }) {
      $r = $f | Get-NetFirewallRule
      $out.rules += @{ name = $r.Name; display = $r.DisplayName; program = $f.Program }
    }
  } catch {}
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


def _tasks_and_rules(item: SoftwareItem, install: Path | None, ctx: ToolContext) -> list[Leftover]:
    target = _normalized(base_name(item.name))
    output = powershell(
        ctx,
        _TASKS_AND_RULES,
        stdin=json.dumps({"install": str(install) if install else ""}),
        timeout_s=90,
    )
    try:
        data = json.loads(output.stdout or "{}")
    except ValueError:
        ctx.warn("No se pudieron leer las tareas programadas ni el firewall")
        return []
    found = []
    needle = str(install).lower() if install else None
    for task in data.get("tasks") or []:
        exe = str(task.get("exe") or "").lower()
        by_path = needle and needle in os.path.expandvars(exe).lower()
        by_name = len(target) >= 4 and target in _normalized(str(task.get("name")))
        if by_path or by_name:
            why = "Ejecuta un programa de su carpeta" if by_path else "Lleva el nombre del programa"
            found.append(Leftover("task", str(task["path"]), why))
    for rule in data.get("rules") or []:
        found.append(
            Leftover(
                "firewall",
                str(rule["name"]),
                f"«{rule.get('display')}» permite {rule.get('program')}",
            )
        )
    return found


def find_leftovers(item: SoftwareItem, ctx: ToolContext) -> list[Leftover]:
    env = ctx.env
    install = _install_folder(item)
    found: dict[str, Leftover] = {}

    def add(leftover: Leftover) -> None:
        found.setdefault(leftover.id, leftover)

    for path, why in _folders(item, env):
        add(Leftover("folder", str(path), why, folder_size(path, ctx, 5)))
    for path in _shortcuts(item, env):
        add(Leftover("file", str(path), "Acceso directo con el nombre del programa"))
    for short, why in [*_registry_keys(item, env.user), *_installer_keys(item, env.user)]:
        add(Leftover("key", short, why))
    for target, why in _run_entries(item, install, env.user):
        add(Leftover("value", target, why))
    if install:
        try:
            services = wmi_rows(CimQuery("root/cimv2", "Win32_Service", ("Name", "PathName")))
        except OSError:
            services = []
        for service in services:
            if str(install).lower() in str(service.get("PathName") or "").lower():
                add(
                    Leftover(
                        "service",
                        str(service.get("Name")),
                        "Su ejecutable está en la carpeta del programa",
                    )
                )
    for leftover in _tasks_and_rules(item, install, ctx):
        add(leftover)
    return list(found.values())


def _leftovers_table(rows: list[dict[str, object]]) -> object:
    return table(
        "restos",
        "Restos encontrados",
        [
            col("kind", "Tipo"),
            col("path", "Ubicación", ColumnKind.PATH),
            col("size", "Tamaño", ColumnKind.BYTES, 2),
            col("evidence", "Por qué", priority=2),
        ],
        rows,
        "id",
        bulk=link("software.remove_leftovers", "Eliminar lo seleccionado", Tone.BAD),
        selection_param="items",
    )


# --- Eliminar un resto --------------------------------------------------------------------------


def _failed(label: str, error: BaseException) -> Check:
    return Check(label=label, status=CheckStatus.FAIL, detail=str(error) or type(error).__name__)


def _remove_key(short: str, value: str, ctx: ToolContext) -> tuple[Check, list[FileRef]]:
    key = user_registry_key(short, ctx.env.user)
    label = f"{short} → {value}" if value else short
    try:
        result = registry_delete.run({"key": key, "value": value}, ctx)
    except (OSError, ValueError, PermissionError, RuntimeError) as error:
        return _failed(label, error), []
    outcome = result.checks[0] if result.checks else Check(label=label, status=CheckStatus.OK)
    return outcome.model_copy(update={"label": label}), list(result.files)


def _remove_service(name: str, ctx: ToolContext) -> tuple[Check, list[FileRef]]:
    label = f"Servicio {name}"
    stopped = stop_service(ctx, name)
    if not stopped:
        ctx.warn(f"El servicio {name} no se detuvo: se elimina igual y termina al reiniciar")
    backup = ctx.backup_path(f"servicio_{name}.reg")
    ctx.command(
        [
            tool_path("reg.exe"),
            "export",
            f"HKLM\\SYSTEM\\CurrentControlSet\\Services\\{name}",
            str(backup),
            "/y",
        ],
        timeout_s=60,
    )
    files = []
    if backup.is_file():
        files.append(FileRef(label=f"Respaldo del servicio {name}", path=str(backup)))
    output = ctx.command([SC, "delete", name], timeout_s=60)
    if output.ok:
        detail = "Eliminado" if stopped else "Eliminado; termina de quitarse al reiniciar"
        status = CheckStatus.OK if stopped else CheckStatus.WARN
        return Check(label=label, status=status, detail=detail), files
    explanation = installer_exit(output.exit_code)
    if explanation.failure is Failure.REBOOT:
        return Check(
            label=label,
            status=CheckStatus.WARN,
            detail="Ya estaba marcado para eliminarse: termina al reiniciar",
            technical=explanation.technical,
        ), files
    return Check(
        label=label,
        status=CheckStatus.FAIL,
        detail=explanation.message,
        technical=f"{explanation.technical}: {output.text[-200:]}",
    ), files


def _remove_task(path: str, ctx: ToolContext) -> tuple[Check, list[FileRef]]:
    label = f"Tarea {path}"
    exported = ctx.command([SCHTASKS, "/query", "/tn", path, "/xml"], timeout_s=30, quiet=True)
    files = []
    if exported.ok:
        backup = ctx.backup_path(f"tarea_{Path(path).name}.xml")
        backup.write_text(exported.stdout, encoding="utf-8")
        files.append(FileRef(label=f"Respaldo de la tarea {path}", path=str(backup)))
    deleted = ctx.command([SCHTASKS, "/delete", "/tn", path, "/f"], timeout_s=30)
    gone = not ctx.command([SCHTASKS, "/query", "/tn", path], timeout_s=30, quiet=True).ok
    if gone:
        return Check(label=label, status=CheckStatus.OK, detail="Eliminada"), files
    return Check(
        label=label,
        status=CheckStatus.FAIL,
        detail="Windows no permitió eliminarla",
        technical=deleted.text[-200:],
    ), files


def _remove_rule(name: str, ctx: ToolContext) -> tuple[Check, list[FileRef]]:
    label = f"Regla del firewall {name}"
    backup = ctx.backup_path(f"firewall_{name[:40]}.json")
    exported = powershell(
        ctx,
        "Get-NetFirewallRule -Name ([Console]::In.ReadToEnd().Trim()) | "
        "Select-Object * | ConvertTo-Json -Depth 3",
        stdin=name,
    )
    files = []
    if exported.ok and exported.stdout.strip():
        backup.write_text(exported.stdout, encoding="utf-8")
        files.append(FileRef(label=f"Respaldo de la regla {name}", path=str(backup)))
    output = powershell(
        ctx,
        "Remove-NetFirewallRule -Name ([Console]::In.ReadToEnd().Trim()) -ErrorAction Stop",
        stdin=name,
    )
    if output.ok:
        return Check(label=label, status=CheckStatus.OK, detail="Eliminada"), files
    return Check(
        label=label,
        status=CheckStatus.FAIL,
        detail="Windows no permitió eliminarla",
        technical=output.text[-200:],
    ), files


def remove_leftover(
    kind: str, target: str, ctx: ToolContext, *, force: bool
) -> tuple[Check, list[FileRef]]:
    try:
        if kind in ("folder", "file"):
            path = Path(target)
            reason = protected(path, ctx.env)
            if reason:
                return Check(
                    label=target, status=CheckStatus.SKIPPED, detail=f"No se toca: {reason}"
                ), []
            return removal.remove(path, ctx, close_apps=True, force=force).check(), []
        if kind == "key":
            return _remove_key(target, "", ctx)
        if kind == "value":
            key, _, value = target.partition("|")
            return _remove_key(key, value, ctx)
        if kind == "service":
            return _remove_service(target, ctx)
        if kind == "task":
            return _remove_task(target, ctx)
        if kind == "firewall":
            return _remove_rule(target, ctx)
    except Exception as error:  # noqa: BLE001 - un resto que falla no detiene los demás
        ctx.error(f"{target}: {error}")
        return _failed(target, error), []
    return Check(label=target, status=CheckStatus.SKIPPED, detail="Tipo desconocido"), []


def _leftover_needs_admin(kind: str, target: str) -> bool:
    if kind in ("folder", "file"):
        return removal.needs_admin(Path(target))
    if kind in ("key", "value"):
        return target.upper().startswith("HKLM")
    return True  # servicios, tareas y reglas del firewall


# --- Desinstalar ---------------------------------------------------------------------------------


def _close_program(install: Path | None, ctx: ToolContext) -> str | None:
    if install is None:
        return None
    try:
        running = processes_using([str(install)])
    except OSError:
        return None
    if not running:
        return None
    names = ", ".join(sorted({p.label for p in running}))
    ctx.info(f"Cerrando lo que usa la carpeta del programa: {names}")
    still = close_processes_using([str(install)])
    if still:
        ctx.warn(f"Sigue abierto: {', '.join(sorted({p.label for p in still}))}")
    return names


def _appx(item: SoftwareItem, ctx: ToolContext) -> ToolResult:
    output = powershell(
        ctx,
        "Remove-AppxPackage -Package ([Console]::In.ReadToEnd().Trim())",
        stdin=item.package_full_name or "",
    )
    left = powershell(
        ctx,
        "if (Get-AppxPackage | ? PackageFullName -eq ([Console]::In.ReadToEnd().Trim())) { exit 1 }",
        stdin=item.package_full_name or "",
    )
    ok = output.ok and left.ok
    return ToolResult(
        checks=[
            check(
                item.name,
                ok,
                "Desinstalada" if ok else "Windows no quitó el paquete",
            ).model_copy(update={"technical": None if ok else output.text[-300:]})
        ],
        verified=ok,
    )


def _run_uninstaller(
    item: SoftwareItem, ctx: ToolContext, *, quiet: bool, timeout_s: float
) -> Check:
    session = ctx.env.user
    ways = _commands(item, quiet, session)
    if not ways:
        return Check(
            label="Desinstalador oficial",
            status=CheckStatus.SKIPPED,
            detail="El programa no registra cómo desinstalarse",
        )
    last: list[int] = []

    def attempt(args: list[str]) -> Callable[[], bool]:
        def run() -> bool:
            code = ctx.command(args, timeout_s=timeout_s).exit_code
            last.append(code)
            return code in _OK_EXIT and not _still_installed(item, session)

        return run

    used = first_that_works(ctx, [Attempt(label, attempt(args)) for label, args in ways])
    if used:
        reboot = last and installer_exit(last[-1]).failure is Failure.REBOOT
        return Check(
            label="Desinstalador oficial",
            status=CheckStatus.WARN if reboot else CheckStatus.OK,
            detail=f"{used}: terminó bien" + ("; pide reiniciar" if reboot else ""),
        )
    explanation = installer_exit(last[-1]) if last else None
    return Check(
        label="Desinstalador oficial",
        status=CheckStatus.FAIL,
        detail=explanation.message if explanation else "No terminó",
        technical=explanation.technical if explanation else None,
    )


def _uninstall(params: Params, ctx: ToolContext) -> ToolResult:
    item = find_item(ctx.env, params["software"])
    mode = params["mode"]
    if item.mechanism is DetectionMechanism.APPX_PACKAGE:
        return _appx(item, ctx)
    session = ctx.env.user
    install = _install_folder(item)
    checks: list[Check] = []
    files: list[FileRef] = []

    closed = _close_program(install, ctx)
    if closed:
        checks.append(
            Check(label="Programa abierto", status=CheckStatus.OK, detail=f"Se cerró {closed}")
        )

    forced = mode == "forced"
    if forced and install:
        # Muchos desinstaladores fallan si su propio servicio sigue en marcha.
        for service in find_services(install):
            ctx.info(f"Deteniendo el servicio {service} antes del desinstalador")
            _stop_quietly(ctx, service)
    uninstaller = _run_uninstaller(
        item,
        ctx,
        quiet=mode != "interactive",
        timeout_s=_FORCED_UNINSTALLER_TIMEOUT_S if forced else 1800,
    )
    checks.append(uninstaller)

    leftovers = find_leftovers(item, ctx)
    if forced:
        ctx.info(f"Modo forzado: eliminando {len(leftovers)} restos")
        # Primero lo que retiene archivos (servicios, tareas), después carpetas y Registro.
        order = {
            "service": 0,
            "task": 1,
            "firewall": 2,
            "value": 3,
            "file": 4,
            "folder": 5,
            "key": 6,
        }
        for leftover in sorted(leftovers, key=lambda lf: order.get(lf.kind, 9)):
            outcome, backups = remove_leftover(leftover.kind, leftover.target, ctx, force=True)
            checks.append(outcome)
            files.extend(backups)
        leftovers = find_leftovers(item, ctx)

    gone = not _still_installed(item, session)
    checks.append(
        Check(
            label=item.name,
            status=CheckStatus.OK if gone else CheckStatus.FAIL,
            detail="Windows ya no lo lista como instalado"
            if gone
            else "Windows lo sigue listando: use el modo forzado",
        )
    )
    pending = any(c.status is CheckStatus.WARN and "reinici" in (c.detail or "") for c in checks)
    summary = [fact("Programa", item.name)]
    if pending:
        summary.append(fact("Reinicio", "Termina de quitarse al reiniciar el equipo", Tone.WARN))
    summary.append(
        fact(
            "Restos",
            len(leftovers) if leftovers else "Ninguno",
            Tone.WARN if leftovers else Tone.OK,
        )
    )
    return ToolResult(
        summary=summary,
        checks=checks,
        tables=[_leftovers_table([lf.row() for lf in leftovers])] if leftovers else [],
        files=files,
        verified=gone,
    )


def find_services(install: Path) -> list[str]:
    try:
        services = wmi_rows(CimQuery("root/cimv2", "Win32_Service", ("Name", "PathName")))
    except OSError:
        return []
    needle = str(install).lower()
    return [str(s.get("Name")) for s in services if needle in str(s.get("PathName") or "").lower()]


def _stop_quietly(ctx: ToolContext, name: str) -> bool:
    try:
        return stop_service(ctx, name, timeout_s=30)
    except (ValueError, OSError):
        return False


def _uninstall_steps(params: Params, env: SupportEnvironment) -> list[PlanStep]:
    item = find_item(env, params["software"])
    if item.mechanism is DetectionMechanism.APPX_PACKAGE:
        return [
            step(
                f"Quitar el paquete {item.package_full_name}",
                f"Remove-AppxPackage {item.package_full_name}",
            )
        ]
    mode = params["mode"]
    ways = _commands(item, mode != "interactive", env.user)
    steps = [step("Cerrar lo que use la carpeta del programa (Restart Manager)")]
    steps += [
        step(
            f"{'Primero' if i == 0 else 'Si falla'}: {label}",
            " ".join(f'"{a}"' if " " in a else a for a in args),
        )
        for i, (label, args) in enumerate(ways)
    ]
    if mode == "forced":
        steps += [
            step("Detener sus servicios"),
            step(
                "Eliminar todos los restos, con respaldo",
                detail="Carpetas, accesos directos, Registro, inicio automático, servicios, "
                "tareas programadas, reglas del firewall y registro de Windows Installer",
            ),
        ]
    else:
        steps.append(step("Buscar los restos que quedaron"))
    return [*steps, step("Comprobar que Windows ya no lo lista")]


def _uninstall_review(params: Params, env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    item = find_item(env, params["software"])
    mode = params["mode"]
    if item.mechanism is DetectionMechanism.APPX_PACKAGE:
        return f"Se quitará la aplicación {item.name} para este usuario.", [], False
    install = _install_folder(item)
    checks: list[Check] = []
    running = running_from([str(install)]) if install else []
    if running:
        names = ", ".join(sorted({p.label for p in running}))
        checks.append(
            Check(
                label="Abierto ahora",
                status=CheckStatus.WARN,
                detail=f"{names}: se cerrará sin guardar",
            )
        )
    ways = _commands(item, mode != "interactive", env.user)
    if ways:
        checks.append(Check(label="Desinstalador", status=CheckStatus.OK, detail=ways[0][0]))
    elif mode != "forced":
        checks.append(
            Check(
                label="Desinstalador",
                status=CheckStatus.FAIL,
                detail="El programa no registra cómo desinstalarse: use el modo forzado",
            )
        )
    location = _registry_location(item)
    needs_admin = bool(location and location[0] == "HKLM") or bool(
        install and removal.needs_admin(install)
    )
    if mode == "forced":
        needs_admin = True
        summary = (
            f"Se quitará {item.name} de raíz: se cierra, se intenta su desinstalador y se elimina "
            "todo lo que deje, con respaldo."
        )
    elif mode == "interactive":
        summary = f"Se abrirá el asistente de {item.name}. Después se buscan sus restos."
    else:
        summary = f"Se desinstalará {item.name} sin preguntas. Después se buscan sus restos."
    return summary, checks, needs_admin


uninstall = SupportTool(
    tool(
        "software.uninstall",
        "Programas",
        "Desinstalar programa",
        "Desinstala con el desinstalador oficial y busca lo que deja. El modo forzado lo quita de "
        "raíz aunque el desinstalador falle o no exista.",
        Risk.DESTRUCTIVE,
        params=[
            text("software", "Programa", required=True, pattern=_ID),
            choice(
                "mode",
                "Modo",
                [
                    ("quiet", "Normal, sin preguntas"),
                    ("interactive", "Con el asistente del programa"),
                    ("forced", "Forzado: de raíz, aunque el desinstalador falle"),
                ],
            ),
        ],
        hidden=True,
    ),
    _uninstall_steps,
    _uninstall,
    backup="Carpetas a la Papelera; Registro, servicios, tareas y reglas del firewall exportados "
    "en HoneyCheck-datos\\respaldos",
    review=_uninstall_review,
)


# --- Buscar y eliminar restos ------------------------------------------------------------------


def _leftovers(params: Params, ctx: ToolContext) -> ToolResult:
    item = find_item(ctx.env, params["software"])
    found = find_leftovers(item, ctx)
    return ToolResult(
        summary=[
            fact("Programa", item.name),
            fact("Restos", len(found) or "Ninguno", Tone.WARN if found else Tone.OK),
        ],
        tables=[_leftovers_table([lf.row() for lf in found])] if found else [],
    )


leftovers = SupportTool(
    tool(
        "software.leftovers",
        "Programas",
        "Buscar restos de un programa",
        "Busca carpetas, accesos directos, Registro, inicio automático, servicios, tareas "
        "programadas y reglas del firewall que un programa dejó, con la evidencia de cada uno.",
        Risk.READ,
        params=[text("software", "Programa", required=True, pattern=_ID)],
        hidden=True,
    ),
    lambda _p, _e: [
        step("Carpeta de instalación, Program Files, ProgramData, AppData y accesos directos"),
        step("Registro del programa, entrada de desinstalación y Windows Installer"),
        step("Inicio automático, servicios, tareas programadas y reglas del firewall"),
    ],
    _leftovers,
)


def _remove_leftovers(params: Params, ctx: ToolContext) -> ToolResult:
    checks: list[Check] = []
    files: list[FileRef] = []
    for entry in params["items"]:
        kind, _, target = entry.partition("|")
        outcome, backups = remove_leftover(kind, target, ctx, force=False)
        checks.append(outcome)
        files.extend(backups)
    return ToolResult(
        checks=checks,
        files=files,
        verified=all(c.status is not CheckStatus.FAIL for c in checks),
    )


def _remove_review(params: Params, env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    items = [entry.partition("|") for entry in params["items"]]
    checks: list[Check] = []
    elevated = bool(env.is_elevated)
    needs_admin = False
    for kind, _, target in items:
        needs_admin = needs_admin or _leftover_needs_admin(kind, target)
        if kind in ("folder", "file"):
            checks.append(removal.inspect(Path(target)).check(elevated=elevated))
        else:
            shown = target.replace("|", " → ") if kind == "value" else target
            checks.append(Check(label=shown, status=CheckStatus.OK, detail=_BACKUP_NOTE.get(kind)))
    what = count_phrase([kind for kind, _, _ in items])
    summary = f"Se eliminarán {what}. Todo queda respaldado."
    return summary, checks, needs_admin


remove_leftovers = SupportTool(
    tool(
        "software.remove_leftovers",
        "Programas",
        "Eliminar restos",
        "Elimina los restos elegidos insistiendo por vías distintas: cierra lo que los usa, "
        "recupera permisos y, si algo de Windows los retiene, los deja para el próximo reinicio.",
        Risk.DESTRUCTIVE,
        params=[multi("items", "Elementos")],
        hidden=True,
    ),
    lambda p, _e: [
        step(f"{KINDS.get(e.partition('|')[0], e)}: {e.partition('|')[2]}") for e in p["items"][:60]
    ],
    _remove_leftovers,
    backup="Carpetas a la Papelera; Registro, servicios, tareas y reglas del firewall exportados "
    "en HoneyCheck-datos\\respaldos",
    review=_remove_review,
)

TOOLS = [uninstall, leftovers, remove_leftovers]
