"""Programas: quitar Microsoft Office por completo (Click-to-Run y MSI).

Desinstalar cualquier otro programa y sus restos vive en `programs.py`."""

from __future__ import annotations

import os
import winreg
from pathlib import Path

from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.inventory import SoftwareItem
from honey_check.domain.support import PlanStep, Risk, Tone, ToolResult

from ..base import Params, SupportTool, check, fact, step, tool
from .programs import MSIEXEC, PRODUCT_CODE

# --- Office ---------------------------------------------------------------------------------------------

_C2R = r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration"
_ODT_CONFIG = """<Configuration>
  <Remove All="TRUE" />
  <Display Level="None" AcceptEULA="TRUE" />
  <Property Name="FORCEAPPSHUTDOWN" Value="TRUE" />
</Configuration>
"""


def _click_to_run() -> dict[str, str] | None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, _C2R, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as key:
            values = {}
            for name in ("ProductReleaseIds", "ClientCulture", "Platform", "VersionToReport"):
                try:
                    values[name] = str(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    continue
            return values
    except OSError:
        return None


def _msi_office(env: SupportEnvironment) -> list[SoftwareItem]:
    if env.inventory is None or env.inventory.software is None:
        return []
    return [
        i
        for i in env.inventory.software.items
        if "microsoft office" in i.name.lower()
        and (i.publisher.value or "").lower().startswith("microsoft")
        and PRODUCT_CODE.match(i.detection_source.rsplit("\\", 1)[-1])
    ]


def _odt(env: SupportEnvironment) -> Path:
    return env.data_root / "herramientas" / "odt" / "setup.exe"


def _office(_params: Params, ctx: ToolContext) -> ToolResult:
    c2r = _click_to_run()
    checks = []
    if c2r:
        config = ctx.output_path("quitar-office.xml")
        config.write_text(_ODT_CONFIG, encoding="utf-8")
        client = (
            Path(os.environ.get("COMMONPROGRAMFILES", r"C:\Program Files\Common Files"))
            / "Microsoft Shared"
            / "ClickToRun"
            / "OfficeClickToRun.exe"
        )
        products = c2r.get("ProductReleaseIds", "")
        culture = c2r.get("ClientCulture", "es-es")
        removals = ",".join(f"{p}.16_{culture}_x-none" for p in products.split(",") if p)
        first_that_works(
            ctx,
            [
                Attempt(
                    "Herramienta de implementación de Office (ODT)",
                    lambda: (
                        _odt(ctx.env).is_file()
                        and ctx.command(
                            [str(_odt(ctx.env)), "/configure", str(config)], timeout_s=3600
                        ).ok
                        and _click_to_run() is None
                    ),
                ),
                Attempt(
                    "Cliente Click-to-Run de Windows",
                    lambda: (
                        client.is_file()
                        and bool(removals)
                        and ctx.command(
                            [
                                str(client),
                                "scenario=install",
                                "scenariosubtype=ARP",
                                "sourcetype=None",
                                f"productstoremove={removals}",
                                f"culture={culture}",
                                "DisplayLevel=False",
                                "forceappshutdown=True",
                            ],
                            timeout_s=3600,
                        ).ok
                        and _click_to_run() is None
                    ),
                ),
            ],
        )
        checks.append(check(f"Office Click-to-Run ({products})", _click_to_run() is None))
    for item in _msi_office(ctx.env):
        code = item.detection_source.rsplit("\\", 1)[-1]
        output = ctx.command([MSIEXEC, "/x", code, "/qn", "/norestart"], timeout_s=3600)
        checks.append(check(item.name, output.exit_code in (0, 1605, 3010)))
    if not checks:
        checks.append(check("Office", None, "No se encontró Microsoft Office instalado"))
    return ToolResult(
        checks=checks,
        summary=[fact("Recomendado", "Reiniciar el equipo al terminar", Tone.WARN)],
        verified=all(c.status.value in ("ok", "skipped") for c in checks),
    )


def _office_steps(_params: Params, env: SupportEnvironment) -> list[PlanStep]:
    steps = []
    c2r = _click_to_run()
    if c2r:
        steps.append(
            step(
                f"Quitar Office Click-to-Run ({c2r.get('ProductReleaseIds')})",
                'setup.exe /configure quitar-office.xml  (<Remove All="TRUE"/>)',
            )
        )
        steps.append(
            step(
                "Si no está la ODT en la USB: cliente Click-to-Run de Windows",
                "OfficeClickToRun.exe scenario=install scenariosubtype=ARP productstoremove=…",
            )
        )
    steps.extend(
        step(f"Desinstalar {i.name}", f"msiexec /x {i.detection_source.rsplit(chr(92), 1)[-1]} /qn")
        for i in _msi_office(env)
    )
    return steps or [step("No se encontró Office instalado")]


office = SupportTool(
    tool(
        "office.remove",
        "Programas",
        "Quitar Microsoft Office por completo",
        "Quita Office Click-to-Run (Microsoft 365, 2016-2024) y las versiones MSI. Usa la ODT si está en HoneyCheck-datos\\herramientas\\odt\\setup.exe.",
        Risk.DESTRUCTIVE,
        admin=True,
    ),
    _office_steps,
    _office,
    warnings=lambda _p, e: (
        ["Se cierran Word, Excel y Outlook sin guardar."]
        + (
            []
            if _odt(e).is_file()
            else ["No está la ODT en la USB: se usará el cliente Click-to-Run del equipo."]
        )
    ),
)

TOOLS = [office]
