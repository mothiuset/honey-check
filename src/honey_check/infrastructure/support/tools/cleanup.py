"""Limpieza: vista previa por categoría y borrado con espacio liberado y archivos omitidos.

Solo se borra contenido de carpetas temporales y cachés conocidas, nunca la carpeta en sí. Los
archivos en uso se omiten y se cuentan. Lo que requiere detener servicios (Windows Update) los
detiene y los vuelve a iniciar aunque el borrado falle.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.support import ColumnKind, PlanStep, Risk, Tone, ToolResult
from honey_check.infrastructure.windows.shell import empty_recycle_bin, recycle_bin_usage

from ..base import Params, SupportTool, check, col, fact, flag, link, multi, step, table, tool
from ..filesystem import is_folder, iter_files
from ..runner import tool_path
from ..winops import start_service, stop_service


def _env(name: str, fallback: str) -> Path:
    return Path(os.environ.get(name) or fallback)


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    folders: tuple[Path, ...]
    admin: bool = False
    min_age_h: float = 0.0
    services: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ("*",)
    note: str | None = None


def categories() -> list[Category]:
    local = _env("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    roaming = _env("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    windows = _env("SYSTEMROOT", r"C:\Windows")
    data = _env("PROGRAMDATA", r"C:\ProgramData")
    return [
        Category(
            "temp_user",
            "Temporales del usuario",
            (_env("TEMP", str(local / "Temp")),),
            min_age_h=24,
            note="Archivos de más de un día",
        ),
        Category(
            "temp_windows", "Temporales de Windows", (windows / "Temp",), admin=True, min_age_h=24
        ),
        Category(
            "browsers",
            "Caché de navegadores",
            (
                local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",
                local / "Microsoft" / "Edge" / "User Data" / "Default" / "Code Cache",
                local / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
                local / "Google" / "Chrome" / "User Data" / "Default" / "Code Cache",
                local / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Cache",
                local / "Mozilla" / "Firefox" / "Profiles",
            ),
            note="No borra contraseñas, historial ni marcadores; cierre los navegadores para liberar más",
        ),
        Category(
            "windows_update",
            "Descargas de Windows Update",
            (windows / "SoftwareDistribution" / "Download",),
            admin=True,
            services=("wuauserv", "bits"),
        ),
        Category(
            "delivery_optimization",
            "Caché de Optimización de distribución",
            (
                windows
                / "ServiceProfiles"
                / "NetworkService"
                / "AppData"
                / "Local"
                / "Microsoft"
                / "Windows"
                / "DeliveryOptimization"
                / "Cache",
            ),
            admin=True,
            services=("dosvc",),
        ),
        Category(
            "crash_dumps",
            "Volcados de memoria y errores",
            (
                windows / "Minidump",
                windows / "LiveKernelReports",
                local / "CrashDumps",
                data / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                data / "Microsoft" / "Windows" / "WER" / "ReportQueue",
            ),
            admin=True,
        ),
        Category(
            "thumbnails",
            "Miniaturas del Explorador",
            (local / "Microsoft" / "Windows" / "Explorer",),
            patterns=("thumbcache_*.db", "iconcache_*.db"),
            note="Las que estén en uso se omiten",
        ),
        Category(
            "office_cache",
            "Caché de Office",
            (local / "Microsoft" / "Office" / "16.0" / "OfficeFileCache",),
            note="Cierre Office antes",
        ),
        Category(
            "teams_cache",
            "Caché de Teams (clásico)",
            (
                roaming / "Microsoft" / "Teams" / "Cache",
                roaming / "Microsoft" / "Teams" / "Service Worker" / "CacheStorage",
            ),
        ),
        Category("recycle_bin", "Papelera de reciclaje", ()),
    ]


def _candidates(category: Category, ctx: ToolContext) -> list[Path]:
    cutoff = time.time() - category.min_age_h * 3600
    found: list[Path] = []
    for folder in category.folders:
        if not is_folder(folder):
            continue
        if category.id == "browsers" and folder.name == "Profiles":
            targets = [p / "cache2" for p in folder.glob("*") if is_folder(p / "cache2")]
        else:
            targets = [folder]
        for target in targets:
            for pattern in category.patterns:
                found.extend(
                    path
                    for path, info in iter_files(
                        target, ctx, recursive=pattern == "*", pattern=pattern
                    )
                    if info.st_mtime <= cutoff
                )
    return found


def _size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _preview(params: Params, ctx: ToolContext) -> ToolResult:
    rows: list[dict[str, Any]] = []
    for index, category in enumerate(categories()):
        ctx.progress(index, len(categories()), category.label)
        if category.id == "recycle_bin":
            size, count = recycle_bin_usage()
        else:
            files = _candidates(category, ctx)
            size, count = _size(files), len(files)
        rows.append(
            {
                "id": category.id,
                "label": category.label,
                "size": size,
                "files": count,
                "admin": category.admin,
                "note": category.note or "",
            }
        )
    total = sum(r["size"] for r in rows)
    return ToolResult(
        summary=[
            fact(
                "Se puede liberar", f"{total / 1024**3:.2f} GiB", Tone.OK if total else Tone.NEUTRAL
            )
        ],
        tables=[
            table(
                "categorias",
                "Categorías",
                [
                    col("label", "Categoría"),
                    col("size", "Tamaño", ColumnKind.BYTES),
                    col("files", "Archivos", ColumnKind.NUMBER, 2),
                    col("admin", "Requiere administrador", ColumnKind.BOOL, 2),
                    col("note", "Nota", priority=3),
                ],
                rows,
                "id",
                bulk=link("cleanup.run", "Limpiar las seleccionadas", Tone.WARN),
                selection_param="categories",
            )
        ],
    )


preview = SupportTool(
    tool(
        "cleanup.preview",
        "Limpieza",
        "Vista previa de limpieza",
        "Calcula cuánto espacio ocupan temporales, cachés, descargas de Windows Update, volcados y la Papelera.",
        Risk.READ,
    ),
    lambda _p, _e: [step(f"Medir {c.label}") for c in categories()],
    _preview,
)


def _delete(paths: list[Path], ctx: ToolContext) -> tuple[int, int]:
    freed = skipped = 0
    for index, path in enumerate(paths):
        if index % 500 == 0:
            ctx.cancel.raise_if_cancelled()
            ctx.progress(index, len(paths), str(path.parent))
        try:
            size = path.stat().st_size
            path.unlink()
            freed += size
        except OSError:
            skipped += 1  # en uso o sin permisos: se deja como está
    return freed, skipped


def _remove_empty_dirs(folder: Path) -> None:
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
        except OSError:
            continue


def _run(params: Params, ctx: ToolContext) -> ToolResult:
    selected = [c for c in categories() if c.id in set(params["categories"])]
    drive = Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\")
    free_before = shutil.disk_usage(drive).free
    checks = []
    for category in selected:
        ctx.info(f"Limpiando: {category.label}")
        if category.admin and not ctx.env.is_elevated:
            checks.append(check(category.label, None, "Requiere administrador: no se limpió"))
            continue
        if category.id == "recycle_bin":
            ok = empty_recycle_bin()
            checks.append(check(category.label, ok, "Vaciada" if ok else "No se pudo vaciar"))
            continue
        stopped = [name for name in category.services if stop_service(ctx, name)]
        try:
            freed, skipped = _delete(_candidates(category, ctx), ctx)
            for folder in category.folders:
                if is_folder(folder) and category.patterns == ("*",):
                    _remove_empty_dirs(folder)
        finally:
            for name in stopped:
                start_service(ctx, name)
        detail = f"{freed / 1024**2:.0f} MiB liberados" + (
            f"; {skipped} archivos en uso se omitieron" if skipped else ""
        )
        checks.append(check(category.label, True, detail, warn=bool(skipped)))
    free_after = shutil.disk_usage(drive).free
    gained = max(0, free_after - free_before)
    return ToolResult(
        summary=[
            fact(
                "Espacio libre ganado en " + str(drive),
                f"{gained / 1024**3:.2f} GiB",
                Tone.OK if gained else Tone.NEUTRAL,
            ),
            fact("Espacio libre ahora", f"{free_after / 1024**3:.1f} GiB"),
        ],
        checks=checks,
        verified=True,
    )


def _run_steps(params: Params, _env_: SupportEnvironment) -> list[PlanStep]:
    chosen = {c.id: c for c in categories()}
    steps = []
    for category_id in params["categories"]:
        category = chosen.get(category_id)
        if category is None:
            continue
        for service in category.services:
            steps.append(step(f"Detener {service}", f"sc stop {service}"))
        if category.id == "recycle_bin":
            steps.append(step("Vaciar la Papelera", "Clear-RecycleBin -Force"))
        for folder in category.folders:
            age = f" con más de {category.min_age_h:g} h" if category.min_age_h else ""
            steps.append(step(f"Borrar el contenido de {folder}{age}", f'del /s /q "{folder}\\*"'))
        for service in category.services:
            steps.append(step(f"Iniciar {service}", f"sc start {service}"))
    return steps


def _run_warnings(params: Params, env: SupportEnvironment) -> list[str]:
    warnings = ["Los archivos borrados no van a la Papelera."]
    needs_admin = [c.label for c in categories() if c.id in params["categories"] and c.admin]
    if needs_admin and not env.is_elevated:
        warnings.append("Sin administrador se omitirán: " + ", ".join(needs_admin))
    return warnings


run = SupportTool(
    tool(
        "cleanup.run",
        "Limpieza",
        "Limpiar",
        "Borra el contenido de las categorías elegidas; omite lo que esté en uso y mide lo liberado.",
        Risk.CHANGE,
        params=[multi("categories", "Categorías")],
        hidden=True,
    ),
    _run_steps,
    _run,
    warnings=_run_warnings,
)

_DISM = tool_path("Dism.exe")


def _components(params: Params, ctx: ToolContext) -> ToolResult:
    drive = Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\")
    before = shutil.disk_usage(drive).free
    args = [_DISM, "/Online", "/Cleanup-Image", "/StartComponentCleanup"]
    if params.get("reset_base"):
        args.append("/ResetBase")
    output = ctx.command(args, timeout_s=3600)
    gained = max(0, shutil.disk_usage(drive).free - before)
    return ToolResult(
        summary=[fact("Espacio liberado", f"{gained / 1024**3:.2f} GiB")],
        checks=[
            check(
                "Limpieza de componentes",
                output.ok,
                output.stdout.strip().splitlines()[-1] if output.stdout.strip() else None,
            )
        ],
        verified=output.ok,
    )


components = SupportTool(
    tool(
        "cleanup.components",
        "Limpieza",
        "Limpiar componentes de Windows (DISM)",
        "Elimina versiones antiguas de componentes de Windows Update. Puede tardar varios minutos.",
        Risk.CHANGE,
        admin=True,
        params=[flag("reset_base", "Hacer permanente (no se podrán desinstalar actualizaciones)")],
    ),
    lambda p, _e: [
        step(
            "Limpiar el almacén de componentes",
            "Dism /Online /Cleanup-Image /StartComponentCleanup"
            + (" /ResetBase" if p.get("reset_base") else ""),
        )
    ],
    _components,
)

TOOLS = [preview, run, components]
