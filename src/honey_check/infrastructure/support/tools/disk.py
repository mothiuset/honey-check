"""Espacio en disco: análisis por carpetas con gráfico, programas por tamaño y enviar a la Papelera."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.support import (
    Chart,
    ChartKind,
    Check,
    Choice,
    ColumnKind,
    PlanStep,
    Risk,
    Tone,
    ToolResult,
)
from honey_check.infrastructure.windows.shell import (
    bring_explorer_forward,
    empty_recycle_bin,
    explorer_windows,
    recycle_bin_usage,
    send_to_recycle_bin,
)
from honey_check.infrastructure.windows.volumes import list_disks

from ..base import (
    Params,
    SupportTool,
    check,
    col,
    fact,
    link,
    multi,
    node_actions,
    number,
    source_multi,
    step,
    table,
    text,
    tool,
)
from ..filesystem import chart_nodes, folder_size, is_folder, scan_tree

_PATH = r"[A-Za-z]:\\[^<>\"|?*\x00]{0,400}"
_EXPLORER = str(Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "explorer.exe")


def _gib(size: int) -> str:
    return f"{size / 1024**3:.1f} GiB"


def _size(size: int) -> str:
    """GiB salvo para lo pequeño (una partición reservada de 16 MiB no es «0.0 GiB»)."""
    return _gib(size) if size >= 1024**3 else f"{size / 1024**2:.0f} MiB"


_FOLDER_ACTIONS = node_actions(
    link("explorer.open", "Abrir en el Explorador", path="{path}"),
    link("disk.analyze", "Analizar aparte", path="{path}"),
)


# Carpetas que Windows administra: analizarlas o abrirlas no lleva a nada útil; se dice qué son y,
# si se puede, qué hacer con ellas.
_SYSTEM_FOLDERS = {
    "$recycle.bin": "Papelera de reciclaje de esta unidad",
    "system volume information": "Puntos de restauración y datos de Windows; se administran en "
    "Protección del sistema",
    "$windows.~bt": "Restos de una actualización de Windows",
    "$windows.~ws": "Restos de una actualización de Windows",
    "windows.old": "Instalación anterior de Windows (permite volver atrás unos días)",
}


def _with_folder_actions(node: dict[str, Any]) -> dict[str, Any]:
    """Cada carpeta del explorador ofrece abrirla y analizarla; el resto agrupado, no. Las del
    sistema dicen qué son y ofrecen su propia acción (vaciar la Papelera de esa unidad)."""
    special = _SYSTEM_FOLDERS.get(str(node.get("name") or "").lower())
    if special:
        node["detail"] = special
        node["actions"] = (
            node_actions(
                link("files.empty_recycle_bin", "Vaciar esta Papelera", Tone.BAD, path="{path}")
            )
            if str(node.get("name")).lower() == "$recycle.bin"
            else []
        )
    elif node.get("path") and not node.get("group"):
        node["actions"] = _FOLDER_ACTIONS
    for child in node.get("children") or []:
        _with_folder_actions(child)
    return node


# --- Analizar espacio ---------------------------------------------------------------------------


def volume_choices() -> list[Choice]:
    """Cada partición de cada disco físico; las que Windows reserva se muestran con su motivo."""
    choices = []
    for disk in list_disks():
        group = f"{disk.title}, {_gib(disk.size)}" + (
            f", {disk.health.lower()}" if disk.health else ""
        )
        for part in disk.partitions:
            used = (
                (part.size - part.free) / part.size if part.free is not None and part.size else None
            )
            space = (
                f"{_gib(part.free)} libres de {_gib(part.size)}"
                if part.free is not None
                else _gib(part.size)
            )
            choices.append(
                Choice(
                    value=part.root or f"particion-{disk.number}-{part.number}",
                    label=part.title,
                    group=group,
                    detail=", ".join(filter(None, [part.file_system, space])),
                    used=round(used, 4) if used is not None else None,
                    disabled_reason=None
                    if part.root
                    else f"{_size(part.size)}, Windows la reserva: no se analiza",
                )
            )
    return choices


SOURCES = {"volumes": volume_choices}


def _relative(path: Path, roots: list[Path]) -> str:
    """La carpeta dentro de lo analizado: la ruta completa repetida en cada fila no se lee."""
    for root in roots:
        try:
            inside = path.relative_to(root)
        except ValueError:
            continue
        if str(inside) == ".":
            return str(root)
        return str(inside) if len(roots) == 1 else str(root / inside)
    return str(path)


def _analyze(params: Params, ctx: ToolContext) -> ToolResult:
    roots = [Path(t) for t in params.get("targets") or []]
    if params.get("path"):
        roots.append(Path(params["path"]))
    if not roots:
        raise ValueError("Elija al menos una unidad o escriba una carpeta")
    missing = [str(r) for r in roots if not is_folder(r)]
    if missing:
        raise ValueError(f"No existe o no se puede abrir: {', '.join(missing)}")
    # Cada unidad en su propio hilo: discos distintos se recorren a la vez.
    with ThreadPoolExecutor(max_workers=min(4, len(roots))) as pool:
        scans = list(pool.map(lambda root: scan_tree(root, ctx), roots))
    for root, scan in zip(roots, scans, strict=True):
        ctx.info(f"{root}: {_gib(scan.root.size)} en {scan.files} archivos")

    largest = sorted((item for scan in scans for item in scan.largest_files), reverse=True)[:60]
    kinds: Counter[str] = Counter()
    for scan in scans:
        kinds.update(scan.by_extension)
    files = [
        {
            "path": path,
            "name": Path(path).name,
            "folder": _relative(Path(path).parent, roots),
            "size": size,
            "modified": datetime.fromtimestamp(mtime, UTC).isoformat(),
        }
        for size, path, mtime in largest
    ]
    trees = [_with_folder_actions(chart_nodes(scan.root, 5)) for scan in scans]
    for root, node in zip(roots, trees, strict=True):
        if str(root) == root.anchor:
            node["name"] = root.anchor.rstrip("\\")
    tree = (
        trees[0]
        if len(trees) == 1
        else {
            "name": "Unidades elegidas",
            "value": sum(int(t["value"]) for t in trees),
            "children": sorted(trees, key=lambda t: -int(t["value"])),
        }
    )
    usage = []
    for anchor in dict.fromkeys(r.anchor for r in roots if r.anchor):
        total, _used, free = shutil.disk_usage(anchor)
        usage.append(
            fact(
                f"Libre en {anchor.rstrip(chr(92))}",
                f"{_gib(free)} de {_gib(total)}",
                Tone.BAD if free / total < 0.1 else Tone.NEUTRAL,
            )
        )
    denied = sum(scan.denied for scan in scans)
    return ToolResult(
        summary=[
            *([fact("Analizado", str(roots[0]))] if len(roots) == 1 else []),
            fact("Tamaño de lo analizado", _gib(sum(s.root.size for s in scans))),
            fact("Archivos", f"{sum(s.files for s in scans):,}".replace(",", ".")),
            fact("Carpetas", f"{sum(s.folders for s in scans):,}".replace(",", ".")),
            *usage,
            *([fact("Sin acceso", denied, Tone.WARN)] if denied else []),
        ],
        charts=[
            Chart(id="arbol", title="Espacio por carpeta", kind=ChartKind.TREEMAP, data=[tree]),
            *(
                [
                    Chart(
                        id="tipos",
                        title="Espacio por tipo de archivo",
                        kind=ChartKind.BAR,
                        data=[{"name": ext, "value": size} for ext, size in kinds.most_common(25)],
                    )
                ]
                if len(kinds) > 1
                else []
            ),
        ],
        tables=[
            table(
                "archivos",
                "Archivos más grandes",
                [
                    col("name", "Archivo"),
                    col("folder", "Carpeta", ColumnKind.PATH, 2),
                    col("size", "Tamaño", ColumnKind.BYTES),
                    col("modified", "Modificado", ColumnKind.DATE, 3),
                ],
                files,
                "path",
                actions=[link("explorer.open", "Mostrar", path="{path}")],
                bulk=link("files.recycle", "Enviar a la Papelera", Tone.BAD),
                selection_param="paths",
            ),
        ],
    )


def _analyze_steps(params: Params, _env: SupportEnvironment) -> list[PlanStep]:
    roots = [*(params.get("targets") or []), *([params["path"]] if params.get("path") else [])]
    return [step(f"Recorrer {r} sin seguir uniones", f'dir "{r}" /s /a') for r in roots] or [
        step("Elegir qué analizar")
    ]


# Huellas: si cambian, el resultado a la vista quedó atrás y la interfaz ofrece actualizarlo.


def _space_state(params: Params) -> str:
    """Espacio libre de cada unidad analizada."""
    roots = [Path(t) for t in params.get("targets") or []]
    if params.get("path"):
        roots.append(Path(params["path"]))
    free = {Path(root).anchor or str(root): shutil.disk_usage(root).free for root in roots}
    return json.dumps(free, sort_keys=True)


def _space_differs(old: str, new: str) -> bool:
    """Más de 1 GiB de diferencia en alguna unidad (los temporales mueven unos megas siempre)."""
    before, now = json.loads(old), json.loads(new)
    return set(before) != set(now) or any(abs(before[k] - now[k]) >= 1024**3 for k in now)


def _programs_state(env: SupportEnvironment) -> str:
    """Los programas registrados ahora (instalar o desinstalar cambia la lista)."""
    from .programs import uninstall_entries  # noqa: PLC0415 - programs importa de este módulo

    entries = sorted(uninstall_entries(env.user))
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


analyze = SupportTool(
    tool(
        "disk.analyze",
        "Espacio en disco",
        "Analizar espacio",
        "Mide cada carpeta de las unidades que elija, de cualquier disco, o de una carpeta, y "
        "muestra dónde se va el espacio y los archivos más grandes.",
        Risk.READ,
        params=[
            source_multi(
                "targets",
                "Unidades",
                "volumes",
                pattern=r"[A-Za-z]:\\",
                help="Particiones de cada disco físico; las que Windows reserva no se analizan.",
            ),
            text("path", "Otra carpeta", pattern=_PATH, help=r"Opcional, por ejemplo C:\Users"),
        ],
    ),
    _analyze_steps,
    _analyze,
    state=lambda p, _e: _space_state(p),
    differs=_space_differs,
)


# --- Programas por tamaño ------------------------------------------------------------------------


def _program_sizes(params: Params, ctx: ToolContext) -> ToolResult:
    from .programs import still_installed, uninstall_entries  # noqa: PLC0415 - importación circular

    inventory = ctx.env.inventory
    if inventory is None or inventory.software is None:
        raise ValueError(
            "Primero analice el equipo: el tamaño se mide desde el inventario de software"
        )
    budget = float(params["budget"])
    # Como en el inventario: los componentes de Windows, marcos y actualizaciones no son programas
    # que el técnico desinstale; llenaban la lista de paquetes Microsoft.* del sistema. Y solo lo
    # que sigue instalado ahora: el inventario puede ser de antes de una desinstalación.
    candidates = [
        i
        for i in inventory.software.items
        if i.install_path.value and not (i.is_system_component or i.is_framework or i.is_update)
    ]
    items = [i for i in candidates if still_installed(i, ctx.env.user)]
    removed = len(candidates) - len(items)
    known = {i.detection_source for i in inventory.software.items}
    newer = [
        name for source, name in uninstall_entries(ctx.env.user).items() if source not in known
    ]
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        ctx.progress(index, len(items), item.name)
        path = Path(str(item.install_path.value))
        measured = folder_size(path, ctx, budget) if is_folder(path) else None
        rows.append(
            {
                "name": item.name,
                "version": item.version.value,
                "measured": measured,
                "declared": item.size_bytes.value,
                "path": str(path),
                "id": item.id,
            }
        )
    rows.sort(key=lambda r: r["measured"] or r["declared"] or 0, reverse=True)
    actions = node_actions(
        link("software.uninstall", "Desinstalar", Tone.BAD, software="{id}"),
        link("software.uninstall", "Desinstalar forzado", Tone.BAD, software="{id}", mode="forced"),
        link("software.leftovers", "Buscar restos", software="{id}"),
        link("explorer.open", "Abrir su carpeta", path="{path}"),
        link("disk.analyze", "Analizar su carpeta", path="{path}"),
    )
    chart = [
        {
            "name": r["name"],
            "value": r["measured"] or r["declared"] or 0,
            "path": r["path"],
            "id": r["id"],
            "detail": ", ".join(
                filter(
                    None,
                    [
                        f"versión {r['version']}" if r["version"] else None,
                        None if r["measured"] else "tamaño declarado por el instalador",
                    ],
                )
            )
            or None,
            "actions": actions,
        }
        for r in rows
        if (r["measured"] or r["declared"])
    ]
    unmeasured = len(rows) - len(chart)
    return ToolResult(
        summary=[
            fact("Programas", len(chart)),
            fact("Ocupan", _gib(sum(c["value"] for c in chart))),
            *([fact("Sin carpeta ni tamaño", unmeasured)] if unmeasured else []),
            *([fact("Desinstalados desde el análisis", removed)] if removed else []),
        ],
        checks=(
            [
                check(
                    "Programas nuevos",
                    False,
                    f"{len(newer)} instalado{'s' if len(newer) != 1 else ''} después del último "
                    "análisis no aparece{n} aquí: analice el equipo para medirlos.".replace(
                        "{n}", "n" if len(newer) != 1 else ""
                    ),
                    warn=True,
                )
            ]
            if newer
            else []
        ),
        charts=[
            Chart(
                id="programas",
                title="Programas por tamaño en disco",
                kind=ChartKind.TREEMAP,
                data=[
                    {
                        "name": "Programas instalados",
                        "value": sum(c["value"] for c in chart),
                        "children": chart,
                    }
                ],
            )
        ],
    )


program_sizes = SupportTool(
    tool(
        "disk.programs",
        "Espacio en disco",
        "Programas por tamaño",
        "Mide en disco la carpeta de cada programa del último análisis y los ordena de mayor a menor.",
        Risk.READ,
        params=[number("budget", "Segundos máximos por programa", default=5)],
    ),
    lambda _p, _e: [step("Medir la carpeta de instalación de cada programa del inventario")],
    _program_sizes,
    state=lambda _p, env: _programs_state(env),
)


# --- Enviar a la Papelera ----------------------------------------------------------------------


def protected(path: Path, env: SupportEnvironment) -> str | None:
    """Motivo por el que la ruta no se puede enviar a la Papelera, o None si se puede."""
    resolved = path.resolve()
    system_root = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows").resolve()
    roots = {
        Path(resolved.anchor),
        Path(os.environ.get("PROGRAMFILES") or r"C:\Program Files"),
        Path(os.environ.get("PROGRAMFILES(X86)") or r"C:\Program Files (x86)"),
        Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData"),
        Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\Users"),
    }
    if resolved in {r.resolve() for r in roots}:
        return "es una carpeta raíz del sistema"
    if resolved.parent == Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\Users").resolve():
        return "es la carpeta de un perfil de usuario"
    if resolved == system_root or system_root in resolved.parents:
        return "está dentro de Windows"
    data = env.data_root.resolve()
    if resolved == data or data in resolved.parents or resolved in data.parents:
        return "es la carpeta de datos de Honey Check"
    return None


def _recycle(params: Params, ctx: ToolContext) -> ToolResult:
    checks = []
    for raw in params["paths"]:
        path = Path(raw)
        reason = protected(path, ctx.env)
        if reason:
            checks.append(check(raw, False, f"No se envió: {reason}"))
            continue
        if not path.exists():
            checks.append(check(raw, None, "Ya no existe"))
            continue
        code = send_to_recycle_bin(str(path))
        gone = not path.exists()
        checks.append(
            check(
                raw,
                gone,
                "En la Papelera (recuperable)"
                if gone
                else f"El Explorador no pudo moverlo (código {code}); puede estar en uso",
            )
        )
        ctx.info(f"{raw}: {'enviado a la Papelera' if gone else 'no se pudo'}")
    return ToolResult(
        checks=checks, verified=all(c.status.value in ("ok", "skipped") for c in checks)
    )


def _recycle_warnings(params: Params, env: SupportEnvironment) -> list[str]:
    blocked = [f"{p}: {r}" for p in params["paths"] if (r := protected(Path(p), env))]
    return ["Estas rutas no se enviarán: " + "; ".join(blocked)] if blocked else []


recycle = SupportTool(
    tool(
        "files.recycle",
        "Espacio en disco",
        "Enviar a la Papelera",
        "Envía archivos o carpetas a la Papelera de reciclaje: se pueden restaurar desde ella.",
        Risk.DESTRUCTIVE,
        params=[multi("paths", "Rutas")],
        hidden=True,
    ),
    lambda p, _e: [step(f"Enviar a la Papelera: {path}") for path in p["paths"][:50]],
    _recycle,
    warnings=_recycle_warnings,
    backup="La Papelera de reciclaje de Windows (se restaura desde ella)",
)


def _open(params: Params, ctx: ToolContext) -> ToolResult:
    path = Path(params["path"])
    args = [_EXPLORER, f"/select,{path}"] if path.is_file() else [_EXPLORER, str(path)]
    ctx.info("Abriendo en el Explorador")
    before = explorer_windows()
    # explorer.exe devuelve 1 aunque abra la ventana: no se usa su código de salida.
    ctx.command(args, timeout_s=15, quiet=True)
    bring_explorer_forward(before)
    return ToolResult(summary=[fact("Abierto", str(path))])


explorer_open = SupportTool(
    tool(
        "explorer.open",
        "Espacio en disco",
        "Abrir en el Explorador",
        "Abre una carpeta o muestra un archivo en el Explorador de Windows.",
        Risk.READ,
        params=[text("path", "Ruta", required=True, pattern=_PATH)],
        hidden=True,
        instant=True,
    ),
    lambda p, _e: [step("Abrir en el Explorador", f'explorer /select,"{p["path"]}"')],
    _open,
)

# --- Vaciar la Papelera de una unidad ---------------------------------------------------------


def _drive_root(path: str) -> str:
    anchor = Path(path).anchor
    if not anchor:
        raise ValueError(f"No es una unidad: {path}")
    return anchor


def _empty_review(params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    root = _drive_root(params["path"])
    size, items = recycle_bin_usage(root)
    if not items:
        return f"La Papelera de {root.rstrip(chr(92))} ya está vacía.", [], False
    what = f"{items} elemento{'s' if items != 1 else ''} ({_size(size)})"
    return (
        f"Se borrarán para siempre {what} de la Papelera de {root.rstrip(chr(92))}.",
        [],
        False,
    )


def _empty(params: Params, _ctx: ToolContext) -> ToolResult:
    root = _drive_root(params["path"])
    before, items = recycle_bin_usage(root)
    empty_recycle_bin(root)
    after, left = recycle_bin_usage(root)
    ok = left == 0
    return ToolResult(
        summary=[fact("Liberado", _size(max(0, before - after)))],
        checks=[
            check(
                f"Papelera de {root.rstrip(chr(92))}",
                ok,
                f"Vacía ({items} elementos borrados)" if ok else f"Quedan {left} elementos en uso",
            )
        ],
        verified=ok,
    )


empty_bin = SupportTool(
    tool(
        "files.empty_recycle_bin",
        "Espacio en disco",
        "Vaciar la Papelera de una unidad",
        "Borra para siempre lo que hay en la Papelera de esa unidad.",
        Risk.DESTRUCTIVE,
        params=[text("path", "Unidad o carpeta de la unidad", required=True, pattern=_PATH)],
        hidden=True,
        action="Vaciar la Papelera",
    ),
    lambda p, _e: [step(f"Vaciar la Papelera de {Path(p['path']).anchor}", "Clear-RecycleBin")],
    _empty,
    review=_empty_review,
)

TOOLS = [analyze, program_sizes, recycle, explorer_open, empty_bin]
