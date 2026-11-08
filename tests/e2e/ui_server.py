"""Servidor real de la interfaz con análisis simulado (datos ficticios) para pruebas de navegador."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support_demo import demo_support

from fakes import FakeAppx, FakeCim, FakeFiles, FakeRegistry, FakeSignatures, make_ports
from fixtures.devices import all_nodes
from fixtures.vendors import ACER, HP
from honey_check.application.collection import CollectionContext
from honey_check.application.ports import (
    CancelToken,
    CimErrorKind,
    FileMetadata,
    RegistryHive,
    RegistryView,
    SignatureResult,
)
from honey_check.application.scan import ScanCoordinator
from honey_check.application.service import CurrentDevice, InventoryService
from honey_check.composition import default_collectors
from honey_check.domain.identity import device_key
from honey_check.infrastructure.collectors.hardware import IdentityCollector
from honey_check.infrastructure.device_store import (
    DeviceInventoryStore,
    InventoryNotFound,
    InventoryUnreadable,
    is_directory_writable,
)
from honey_check.presentation.http.app import AppCallbacks, create_app
from honey_check.presentation.http.security import SessionGuard
from honey_check.presentation.http.server import LocalServer

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
HOSTILE_NAME = '<img src=x onerror="window.__xss=1">Programa <b>hostil</b>'
EDITOR_EXE = "C:\\Program Files\\Editor Ficticio\\editor.exe"


class _FakeTree:
    def nodes(self, _classes: Any) -> list[Any]:
        return all_nodes()


def demo_ports(rows: dict[str, Any] | None = None) -> Any:
    hklm, hkcu = RegistryHive.LOCAL_MACHINE, RegistryHive.CURRENT_USER
    v64, v32, default = RegistryView.BITS_64, RegistryView.BITS_32, RegistryView.DEFAULT
    registry = FakeRegistry()
    registry.put(
        hklm,
        v64,
        f"{UNINSTALL}\\Editor",
        {
            "DisplayName": "Editor Ficticio",
            "DisplayVersion": "4.2.1",
            "Publisher": "Editorial Ficticia",
            "InstallLocation": "C:\\Program Files\\Editor Ficticio",
            "DisplayIcon": f"{EDITOR_EXE},0",
            "UninstallString": '"C:\\Program Files\\Editor Ficticio\\unins000.exe" /S',
            "InstallDate": "20260115",
            "EstimatedSize": 204800,
        },
    )
    registry.put(
        hklm,
        v32,
        f"{UNINSTALL}\\Visor",
        {
            "DisplayName": "Visor Antiguo",
            "DisplayVersion": "1.0",
            "UninstallString": "MsiExec.exe /X{12345678-90AB-CDEF-1234-567890ABCDEF}",
        },
    )
    registry.put(hkcu, default, f"{UNINSTALL}\\Hostil", {"DisplayName": HOSTILE_NAME})
    registry.put(
        hklm, v64, f"{UNINSTALL}\\Comp", {"DisplayName": "Componente interno", "SystemComponent": 1}
    )
    registry.put(
        hklm,
        default,
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        {"EditionID": "Enterprise", "DisplayVersion": "24H2", "UBR": 4321, "CurrentBuild": "26100"},
    )
    files = FakeFiles(
        existing={EDITOR_EXE, "C:\\Program Files\\Editor Ficticio\\unins000.exe"},
        directories={"C:\\Program Files\\Editor Ficticio": []},
        metadata_by_path={
            EDITOR_EXE: FileMetadata(
                file_version="4.2.1.0",
                product_version="4.2.1",
                product_name="Editor",
                machine="x64",
            )
        },
    )
    signatures = FakeSignatures({EDITOR_EXE: SignatureResult("valid", "CN=Editorial Ficticia")})
    cim_rows = {
        **HP,
        "Win32_OperatingSystem": [
            {
                "Caption": "Microsoft Windows 11 Enterprise",
                "Version": "10.0.26100",
                "BuildNumber": "26100",
                "OSArchitecture": "64-bit",
                "InstallDate": "2025-06-01T12:00:00.0000000Z",
                "LastBootUpTime": "2026-11-01T08:00:00.0000000Z",
                "Locale": "240a",
            }
        ],
        "Win32_QuickFixEngineering": [
            {
                "HotFixID": "KB0000001",
                "Description": "Security Update",
                "InstalledOn": "2026-10-20T05:00:00Z",
            }
        ],
        "MSFT_Partition": [
            {
                "DiskNumber": 0,
                "PartitionNumber": 0,
                "DriveLetter": 0,
                "Size": 100 * 1024**2,
                "GptType": "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}",
                "AccessPaths": [],
            },
            {
                "DiskNumber": 0,
                "PartitionNumber": 1,
                # Por COM la letra llega como número: 67 es «C».
                "DriveLetter": 67,
                "Size": 200 * 1024**3,
                "GptType": "{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}",
                "AccessPaths": ["C:\\"],
            },
        ],
        "MSFT_Volume": [
            {
                "Path": "\\\\?\\Volume{c}\\",
                "DriveLetter": "C",
                "FileSystemLabel": "Sistema",
                "FileSystem": "NTFS",
                "Size": 200 * 1024**3,
                "SizeRemaining": 80 * 1024**3,
            }
        ],
        "Win32_Battery": [
            {
                "Name": "BAT-FICTICIA",
                "EstimatedChargeRemaining": 76,
                "BatteryStatus": 2,
                "Chemistry": 6,
            }
        ],
        "Win32_PnPEntity": [
            {
                "Name": "Lector Ficticio",
                "PNPClass": "SmartCardReader",
                "ConfigManagerErrorCode": 28,
                "Status": "Error",
                "DeviceID": "PCI\\VEN_FFFF",
            }
        ],
        **(rows or {}),
    }
    ports = make_ports(
        cim=FakeCim(
            cim_rows,
            {
                "Win32_Tpm": CimErrorKind.ACCESS_DENIED,
                "Win32_EncryptableVolume": CimErrorKind.ACCESS_DENIED,
            },
        ),
        registry=registry,
        files=files,
        signatures=signatures,
        appx=FakeAppx(
            rows=[
                {
                    "Name": "Empresa.AppTienda",
                    "Publisher": "CN=Empresa Ficticia",
                    "Version": "2.0.0.0",
                    "Architecture": "X64",
                    "PackageFullName": "Empresa.AppTienda_2.0.0.0_x64__abc",
                    "SignatureKind": "Store",
                }
            ]
        ),
    )
    # Un árbol de dispositivos ficticio: aparatos agrupados y no conectados.
    ports.devices = _FakeTree()
    return ports


@dataclass
class UiServer:
    server: LocalServer
    guard: SessionGuard
    service: InventoryService
    exit_requests: list[int]
    directory: Path
    support: Any = None

    def entry_url(self) -> str:
        return f"{self.server.base_url}/auth/{self.guard.issue_ticket()}"

    def stop(self) -> None:
        self.service.shutdown()
        if self.support:
            self.support[0].shutdown()
        self.server.stop()


def scan_into(directory: Path, ports: Any) -> None:
    """Guarda un análisis de otro equipo ficticio, como los que trae una USB usada en varios PCs."""
    received: list[Any] = []
    coordinator = ScanCoordinator(default_collectors(), ports, "0.1.0", None, received.append)
    coordinator.start()
    assert coordinator.wait(30)
    DeviceInventoryStore(directory).save(received[0])


def other_device_ports() -> Any:
    return make_ports(cim=FakeCim(ACER), appx=FakeAppx())


def start_ui_server(directory: Path, ports: Any = None, known_device: bool = True) -> UiServer:
    guard = SessionGuard()
    exit_requests: list[int] = []
    service = InventoryService(
        DeviceInventoryStore(directory),
        lambda done: ScanCoordinator(
            default_collectors(), ports or demo_ports(), "0.1.0", "abc1234", done
        ),
        is_directory_writable,
        is_network_path=lambda _: False,
    )
    support = demo_support(directory)

    def factory(port: Any) -> Any:
        return create_app(
            service,
            guard,
            port,
            "0.1.0",
            AppCallbacks(lambda _: None, lambda: exit_requests.append(1)),
            (InventoryNotFound, InventoryUnreadable),
            support=support,
        )

    if known_device:
        # Lo que en la aplicación hace la sonda inicial del equipo.
        identity = IdentityCollector().collect(
            CollectionContext("identity", ports or demo_ports(), CancelToken(), 10)
        )
        key = device_key(identity)
        service.set_current_device(
            CurrentDevice(key.value, key.basis.value, identity.hostname.value)
        )

    server = LocalServer(factory, guard.instance_id)
    server.start()
    return UiServer(server, guard, service, exit_requests, directory, support)
