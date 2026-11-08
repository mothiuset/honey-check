"""«Windows dañado»: comprobar primero lo rápido, reparar solo lo necesario y mostrar el avance.

Orden (el de Microsoft, sin pasos de más): estado del almacén de componentes en segundos
(Repair-WindowsImage -CheckHealth, que responde con un valor fijo en cualquier idioma); si está
dañado, DISM lo repara con su avance en vivo; después SFC revisa y repara los archivos del sistema,
también con avance. Lo que SFC hizo se lee del CBS.log (siempre en inglés): archivos reparados o
que no pudo reparar. Si quedó algo sin reparar y DISM no había corrido, se repara el almacén y SFC
vuelve a pasar. Un reinicio pendiente bloquea antes de empezar: Windows no repara así.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.support import Check, CheckStatus, Risk, ToolResult

from ..base import Params, SupportTool, fact, step, tool
from ..runner import tool_path
from ..winops import powershell
from .updates import pending_reboot

DISM = tool_path("dism.exe")
SFC = tool_path("sfc.exe")
_MIN_FREE = 5 * 1024**3
_PERCENT = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_CBS_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
# Repair-WindowsImage devuelve ImageHealthState: 0 sano, 1 reparable, 2 no reparable.
_HEALTH = {0: "Sano", 1: "Dañado, se puede reparar", 2: "Dañado y DISM no puede repararlo solo"}
_CHECK = (
    "$ErrorActionPreference='Stop'; "
    "[int](Repair-WindowsImage -Online -CheckHealth).ImageHealthState"
)

# --- Lo que se lee del equipo -------------------------------------------------------------------


def cbs_log() -> Path:
    return Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "Logs" / "CBS" / "CBS.log"


@dataclass(frozen=True)
class SfcReport:
    repaired: int = 0
    unrepaired: int = 0
    verified: bool = False
    last: datetime | None = None


def cbs_size() -> int:
    try:
        return cbs_log().stat().st_size
    except OSError:
        return 0


def sfc_report(offset: int = 0) -> SfcReport:
    """Lo que SFC dejó en CBS.log (líneas «[SR]») desde la posición `offset`: así una pasada
    nunca cuenta lo de la anterior, aunque las dos caigan en el mismo segundo."""
    try:
        with cbs_log().open("rb") as handle:
            # Si Windows rotó el registro durante la pasada, el archivo nuevo empieza de cero.
            handle.seek(offset if offset <= cbs_size() else 0)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return SfcReport()
    repaired = unrepaired = 0
    verified = False
    last = None
    for line in text.splitlines():
        if "[SR]" not in line:
            continue
        match = _CBS_TIME.match(line)
        stamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") if match else None
        last = stamp or last
        if "Cannot repair" in line:
            unrepaired += 1
        elif "Repairing corrupted file" in line or "Repaired file" in line:
            repaired += 1
        elif "Verify complete" in line:
            verified = True
    return SfcReport(repaired, unrepaired, verified, last)


def _files(count: int) -> str:
    return "1 archivo" if count == 1 else f"{count} archivos"


def system_free_bytes() -> int:
    return shutil.disk_usage(os.environ.get("SYSTEMDRIVE", "C:") + "\\").free


def _live(ctx: ToolContext, label: str) -> Callable[[str], None]:
    """El porcentaje que imprimen DISM y SFC, como avance de la ejecución."""

    def feed(text: str) -> None:
        found = _PERCENT.findall(text)
        if found:
            value = float(found[-1].replace(",", "."))
            ctx.progress(min(100, int(value)), 100, label)

    return feed


def store_health(ctx: ToolContext) -> int | None:
    ctx.progress(0, 0, "Revisando el almacén de componentes (segundos)")
    output = powershell(ctx, _CHECK, timeout_s=300)
    try:
        return int(output.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


# --- Revisión previa ----------------------------------------------------------------------------


def _review(_params: Params, _env: SupportEnvironment) -> tuple[str, list[Check], bool]:
    checks = []
    reboot = pending_reboot()
    if reboot:
        checks.append(
            Check(
                label="Reinicio pendiente",
                status=CheckStatus.FAIL,
                detail=f"Windows espera un reinicio ({', '.join(reboot)}) y no repara así. "
                "Reinicie y vuelva a abrir esta herramienta.",
            )
        )
    free = system_free_bytes()
    if free < _MIN_FREE:
        checks.append(
            Check(
                label="Poco espacio",
                status=CheckStatus.WARN,
                detail=f"Quedan {free / 1024**3:.1f} GiB; DISM puede necesitar varios GiB.",
            )
        )
    last = sfc_report()
    if last.last:
        when = f"{last.last:%d/%m/%Y}"
        if last.unrepaired:
            detail = f"El {when} SFC no pudo reparar {_files(last.unrepaired)}."
            status = CheckStatus.WARN
        elif last.repaired:
            detail = f"El {when} SFC reparó {_files(last.repaired)}."
            status = CheckStatus.INFO
        else:
            detail = f"El {when} SFC no encontró problemas."
            status = CheckStatus.INFO
        checks.append(Check(label="Última comprobación", status=status, detail=detail))
    if reboot:
        return "Hay un reinicio pendiente: reinicie antes de reparar.", checks, True
    return (
        "Se revisa el almacén de componentes (segundos) y los archivos del sistema con SFC (10 a "
        "15 minutos, con avance). DISM repara solo si hace falta.",
        checks,
        True,
    )


# --- Ejecución -----------------------------------------------------------------------------------


def _restore(ctx: ToolContext) -> Check:
    output = ctx.command(
        [DISM, "/Online", "/Cleanup-Image", "/RestoreHealth", "/NoRestart"],
        timeout_s=3600,
        quiet=True,
        on_output=_live(ctx, "Reparando el almacén de componentes (DISM)"),
    )
    if output.ok:
        return Check(
            label="Reparar el almacén de componentes",
            status=CheckStatus.OK,
            detail="DISM lo reparó",
        )
    return Check(
        label="Reparar el almacén de componentes",
        status=CheckStatus.FAIL,
        detail="DISM no pudo repararlo con Windows Update: hace falta un medio de instalación de "
        "la misma versión de Windows como origen.",
        technical=output.text[-300:],
    )


def _sfc(ctx: ToolContext) -> tuple[Check, SfcReport]:
    offset = cbs_size()
    output = ctx.command(
        [SFC, "/scannow"],
        timeout_s=3600,
        quiet=True,
        on_output=_live(ctx, "Revisando los archivos del sistema (SFC)"),
    )
    report = sfc_report(offset)
    if report.unrepaired:
        status, detail = (
            CheckStatus.FAIL,
            f"No pudo reparar {_files(report.unrepaired)}"
            + (f"; {report.repaired} sí" if report.repaired else ""),
        )
    elif report.repaired:
        status, detail = CheckStatus.OK, f"Reparó {_files(report.repaired)}"
    elif output.ok or report.verified:
        status, detail = CheckStatus.OK, "No encontró archivos dañados"
    else:
        status, detail = CheckStatus.FAIL, "SFC no terminó"
    return (
        Check(
            label="Archivos del sistema",
            status=status,
            detail=detail,
            technical=None if status is CheckStatus.OK else output.text[-300:],
        ),
        report,
    )


def _repair(_params: Params, ctx: ToolContext) -> ToolResult:
    reboot = pending_reboot()
    if reboot:
        raise ValueError("Hay un reinicio pendiente: reinicie antes de reparar")
    checks: list[Check] = []
    health = store_health(ctx)
    checks.append(
        # Cómo estaba al empezar: un dato, no un resultado (el resultado es el estado al terminar).
        Check(
            label="Almacén de componentes al empezar",
            status=CheckStatus.OK if health == 0 else CheckStatus.INFO,
            detail=_HEALTH.get(health or 0, "No se pudo leer")
            if health is not None
            else "No se pudo leer",
        )
    )
    restored = False
    if health in (1, 2):
        ctx.info("El almacén está dañado: se repara antes de revisar los archivos")
        checks.append(_restore(ctx))
        restored = True
    sfc_check, report = _sfc(ctx)
    checks.append(sfc_check)
    if report.unrepaired and not restored:
        # Microsoft: si SFC no puede reparar, se repara el almacén y SFC vuelve a pasar.
        ctx.info("SFC no pudo reparar todo: se repara el almacén y se vuelve a revisar")
        checks.append(_restore(ctx))
        sfc_check, report = _sfc(ctx)
        checks.append(
            sfc_check.model_copy(update={"label": "Archivos del sistema (segunda pasada)"})
        )
    final = store_health(ctx)
    if final is not None:
        checks.append(
            Check(
                label="Almacén de componentes al terminar",
                status=CheckStatus.OK if final == 0 else CheckStatus.FAIL,
                detail=_HEALTH.get(final, "Sin dato"),
            )
        )
    changed = restored or report.repaired > 0
    return ToolResult(
        summary=[
            fact("Archivos reparados", report.repaired),
            *([fact("Siguiente paso", "Reinicie el equipo para terminar")] if changed else []),
        ],
        checks=checks,
        verified=final == 0 and not report.unrepaired,
    )


repair = SupportTool(
    tool(
        "system.repair",
        "Sistema",
        "Windows dañado",
        "Revisa en segundos el almacén de componentes, repara con DISM solo si hace falta y "
        "revisa los archivos del sistema con SFC, con avance en vivo; dice qué reparó.",
        Risk.CHANGE,
        admin=True,
        action="Revisar y reparar Windows",
    ),
    lambda _p, _e: [
        step("Estado del almacén de componentes", "Repair-WindowsImage -Online -CheckHealth"),
        step("Si está dañado: repararlo", "DISM /Online /Cleanup-Image /RestoreHealth"),
        step("Revisar y reparar archivos del sistema", "sfc /scannow"),
        step("Si SFC no pudo: reparar el almacén y repetir SFC"),
        step("Comprobar el almacén al terminar"),
    ],
    _repair,
    review=_review,
)

TOOLS = [repair]
