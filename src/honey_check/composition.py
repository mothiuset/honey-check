"""Raíz de composición: el único lugar que conoce los adaptadores concretos."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from honey_check.application.collection import CollectionContext, Collector
from honey_check.application.ports import CancelToken, CollectorPorts
from honey_check.application.service import CurrentDevice
from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment, Tool, UserSession
from honey_check.application.support.procedures import ProcedureService
from honey_check.domain.identity import device_key
from honey_check.domain.inventory import Inventory
from honey_check.infrastructure.collectors.hardware import (
    IdentityCollector,
    MemoryCollector,
    ProcessorCollector,
    StorageCollector,
)
from honey_check.infrastructure.collectors.peripherals import PeripheralsCollector
from honey_check.infrastructure.collectors.software import SoftwareCollector
from honey_check.infrastructure.collectors.system import (
    BatteryCollector,
    DevicesCollector,
    DisplayCollector,
    GraphicsCollector,
    NetworkCollector,
    OperatingSystemCollector,
    SecurityCollector,
    TpmCollector,
)
from honey_check.infrastructure.support import elevated
from honey_check.infrastructure.support.journal import FileRunJournal
from honey_check.infrastructure.support.procedure_store import FileProcedureStore
from honey_check.infrastructure.support.runner import SystemCommandRunner
from honey_check.infrastructure.support.tools import (
    certificates,
    cleanup,
    connectivity,
    credentials,
    devices,
    disk,
    domain,
    drivers,
    network,
    policies,
    printer_drivers,
    printers,
    printing,
    programs,
    registry,
    repair,
    software,
    system,
    updates,
)
from honey_check.infrastructure.support.tools.procedures import procedure_tools
from honey_check.infrastructure.windows.browser import AppWindow
from honey_check.infrastructure.windows.devnodes import WinDeviceTree
from honey_check.infrastructure.windows.elevation import ElevatedProcess
from honey_check.infrastructure.windows.files import WinFileInspector, is_network_path
from honey_check.infrastructure.windows.icons import WinIconExtractor
from honey_check.infrastructure.windows.native import WinNativeSystem
from honey_check.infrastructure.windows.powershell import (
    PowerShell,
    PowerShellAppx,
    PowerShellCim,
    PowerShellInfo,
)
from honey_check.infrastructure.windows.process import ProcessRunner
from honey_check.infrastructure.windows.registry import WinRegistry
from honey_check.infrastructure.windows.session import current_session
from honey_check.infrastructure.windows.wintrust import WinTrustSignatures
from honey_check.infrastructure.windows.wmi import CimWithFallback, WmiCim


def default_collectors() -> list[Collector]:
    """Catálogo de módulos de inventario. Añadir un módulo es añadir una línea aquí."""
    # El software es el módulo más largo: arranca primero para no alargar el análisis.
    return [
        SoftwareCollector(),
        IdentityCollector(),
        ProcessorCollector(),
        MemoryCollector(),
        StorageCollector(),
        OperatingSystemCollector(),
        GraphicsCollector(),
        DisplayCollector(),
        NetworkCollector(),
        BatteryCollector(),
        TpmCollector(),
        DevicesCollector(),
        PeripheralsCollector(),
        SecurityCollector(),
    ]


def windows_ports(runner: ProcessRunner) -> CollectorPorts:
    powershell = PowerShell(runner)
    return CollectorPorts(
        # WMI nativo por COM; PowerShell solo como respaldo ante fallos inesperados.
        cim=CimWithFallback(WmiCim(), PowerShellCim(powershell)),
        registry=WinRegistry(),
        files=WinFileInspector(),
        signatures=WinTrustSignatures(),
        native=WinNativeSystem(),
        appx=PowerShellAppx(powershell),
        powershell=PowerShellInfo(powershell),
        icons=WinIconExtractor(),
        devices=WinDeviceTree(),
    )


_PROBE_TIMEOUT_S = 20.0


def probe_current_device(runner: ProcessRunner) -> CurrentDevice | None:
    """Identifica el equipo actual al arrancar, con el mismo módulo que usa el análisis."""
    collector = IdentityCollector()
    context = CollectionContext(
        module=collector.name,
        ports=windows_ports(runner),
        cancel=CancelToken(),
        timeout_s=_PROBE_TIMEOUT_S,
    )
    try:
        identity = collector.collect(context)
    except Exception as error:  # noqa: BLE001 - sin sonda, el análisis identificará el equipo
        logging.getLogger(__name__).info("Sonda de equipo sin resultado: %s", type(error).__name__)
        return None
    key = device_key(identity)
    return CurrentDevice(key.value, key.basis.value, identity.hostname.value)


def is_network_export_path(path: str) -> bool:
    return is_network_path(path)


def open_interface(url: str, data_root: Path) -> bool:
    """Abre la interfaz con el perfil del navegador dentro de la carpeta de datos."""
    return AppWindow(data_root).open(url)


def close_interface(data_root: Path) -> None:
    """Cierra la ventana que abrió Honey Check: usa archivos de la carpeta de datos."""
    AppWindow(data_root).close()


def support_tools(procedures: ProcedureService) -> list[Tool]:
    """Catálogo de herramientas de soporte. Añadir una es añadir su módulo aquí."""
    catalog: dict[str, Tool] = {}
    tools: list[Tool] = [
        *disk.TOOLS,
        *cleanup.TOOLS,
        *programs.TOOLS,
        *software.TOOLS,
        *printing.TOOLS,
        *printers.TOOLS,
        *printer_drivers.TOOLS,
        *connectivity.TOOLS,
        *network.TOOLS,
        *policies.TOOLS,
        *domain.TOOLS,
        *certificates.TOOLS,
        *devices.TOOLS,
        *drivers.TOOLS,
        *updates.TOOLS,
        *repair.TOOLS,
        *system.TOOLS,
        *registry.TOOLS,
        *credentials.TOOLS,
    ]
    tools.extend(procedure_tools(procedures, lambda: catalog))
    catalog.update({tool.definition.id: tool for tool in tools})
    return tools


def support_services(
    data_root: Callable[[], Path],
    runner: ProcessRunner,
    environment: Callable[[], tuple[bool | None, object]],
    launch_worker: Callable[[list[str]], ElevatedProcess] | None = None,
) -> tuple[SupportEngine, ProcedureService]:
    """Motor de soporte y procesos de instalación, con sus datos en la carpeta de datos."""
    procedures = ProcedureService(FileProcedureStore(data_root))
    command_runner = SystemCommandRunner(runner)
    session = current_session()

    def build_environment() -> SupportEnvironment:
        elevated, inventory = environment()
        return SupportEnvironment(
            data_root=data_root(),
            runner=command_runner,
            is_elevated=elevated,
            inventory=inventory,  # type: ignore[arg-type]
            user=session,
        )

    engine = SupportEngine(
        support_tools(procedures),
        FileRunJournal(data_root),
        build_environment,
        elevated.ElevatedToolRunner(launch_worker) if launch_worker else None,
        sources={**disk.SOURCES, **printing.SOURCES, **printer_drivers.SOURCES},
    )
    return engine, procedures


def serve_support_worker(address: str, key_hex: str, runner: ProcessRunner) -> int:
    """Proceso elevado de una sola acción (ver infrastructure/support/elevated.py)."""
    root: list[Path] = []
    procedures = ProcedureService(FileProcedureStore(lambda: root[0]))
    tools = {tool.definition.id: tool for tool in support_tools(procedures)}
    command_runner = SystemCommandRunner(runner)

    def environment(
        data_root: Path, inventory: Inventory | None, user: UserSession | None
    ) -> SupportEnvironment:
        root.append(data_root)
        return SupportEnvironment(
            data_root=data_root,
            runner=command_runner,
            is_elevated=True,
            inventory=inventory,
            user=user,
        )

    return elevated.serve(address, key_hex, tools, environment)
