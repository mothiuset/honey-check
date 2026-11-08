"""Módulos de sistema, periféricos y seguridad con respuestas simuladas (mocks)."""

from __future__ import annotations

from typing import Any

import pytest

from fakes import FakeCim, FakeNative, FakePowerShellInfo, FakeRegistry, make_context, make_ports
from honey_check.application.collection import ModuleFailed
from honey_check.application.ports import CimErrorKind, RegistryHive, RegistryView, TpmNativeInfo
from honey_check.domain.observed import Confidence, Reason
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

CURRENT_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"


def context_for(
    rows: dict[str, list[dict[str, Any]]] | None = None,
    errors: dict[str, CimErrorKind] | None = None,
    **kwargs: Any,
) -> Any:
    return make_context(make_ports(cim=FakeCim(rows, errors), **kwargs))


def os_registry(**values: Any) -> FakeRegistry:
    registry = FakeRegistry()
    registry.put(RegistryHive.LOCAL_MACHINE, RegistryView.DEFAULT, CURRENT_VERSION, values)
    return registry


def os_row(caption: str, build: str) -> dict[str, Any]:
    return {
        "Caption": caption,
        "Version": f"10.0.{build}",
        "BuildNumber": build,
        "OSArchitecture": "64-bit",
        "InstallDate": "2025-06-01T12:00:00.0000000Z",
        "LastBootUpTime": "2026-11-01T08:00:00.0000000Z",
        "Locale": "240a",
    }


class TestOperatingSystem:
    @pytest.mark.parametrize(
        ("caption", "build", "edition", "version", "generation", "ltsc"),
        [
            ("Microsoft Windows 10 Pro", "19045", "Professional", "22H2", "windows_10", False),
            (
                "Microsoft Windows 10 Enterprise LTSC",
                "17763",
                "EnterpriseS",
                None,
                "windows_10",
                True,
            ),
            ("Microsoft Windows 11 Pro", "22631", "Professional", "23H2", "windows_11", False),
            ("Microsoft Windows 11 Enterprise", "26100", "Enterprise", "24H2", "windows_11", False),
            (
                "Microsoft Windows 11 IoT Enterprise LTSC",
                "26100",
                "IoTEnterpriseS",
                "24H2",
                "windows_11",
                True,
            ),
        ],
    )
    def test_editions(self, caption, build, edition, version, generation, ltsc) -> None:
        registry = os_registry(
            EditionID=edition, DisplayVersion=version, UBR=1234, CurrentBuild=build
        )
        section = OperatingSystemCollector().collect(
            context_for({"Win32_OperatingSystem": [os_row(caption, build)]}, registry=registry)
        )
        assert section.name.value == caption
        assert section.generation.value == generation
        assert section.is_ltsc.value is ltsc
        assert section.edition_id.value == edition
        assert section.full_build.value == f"{build}.1234"
        assert section.installed_at.value.year == 2025

    def test_windows_11_product_name_of_registry_is_not_used(self) -> None:
        """El Registro sigue diciendo «Windows 10» en Windows 11."""
        registry = os_registry(ProductName="Windows 10 Pro", EditionID="Professional", UBR=1)
        section = OperatingSystemCollector().collect(
            context_for(
                {"Win32_OperatingSystem": [os_row("Microsoft Windows 11 Pro", "22631")]},
                registry=registry,
            )
        )
        assert section.name.value == "Microsoft Windows 11 Pro"

    def test_hotfixes(self) -> None:
        rows = {
            "Win32_OperatingSystem": [os_row("W", "19045")],
            "Win32_QuickFixEngineering": [
                {"HotFixID": "KB0000001", "Description": "Update", "InstalledOn": "1/2/2026"},
                {"HotFixID": "File 1", "Description": None, "InstalledOn": None},
            ],
        }
        section = OperatingSystemCollector().collect(context_for(rows, registry=os_registry()))
        assert section.hotfix_count.value == 2
        assert section.hotfixes[0].installed_on_raw == "1/2/2026"

    def test_hotfix_failure_is_partial(self) -> None:
        ctx = context_for(
            {"Win32_OperatingSystem": [os_row("W", "19045")]},
            {"Win32_QuickFixEngineering": CimErrorKind.TRANSIENT},
            registry=os_registry(UBR=1),
        )
        section = OperatingSystemCollector().collect(ctx)
        assert section.hotfix_count.value is None
        assert section.hotfix_count.reason == Reason.QUERY_FAILED
        assert section.name.value == "W"
        assert ctx.errors

    def test_wmi_failure_uses_registry_build(self) -> None:
        section = OperatingSystemCollector().collect(
            context_for(
                {},
                {"Win32_OperatingSystem": CimErrorKind.FAILED},
                registry=os_registry(CurrentBuild="19045", UBR=5, EditionID="Enterprise"),
            )
        )
        assert section.name.value is None
        assert section.build.value == 19045
        assert section.generation.value == "windows_10"

    def test_total_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            OperatingSystemCollector().collect(
                context_for(
                    {}, {"Win32_OperatingSystem": CimErrorKind.FAILED}, registry=FakeRegistry()
                )
            )


class TestGraphics:
    def base(self, **extra: Any) -> dict[str, Any]:
        return {
            "Name": "Grafica Ficticia",
            "AdapterCompatibility": "Fabricante Ficticio",
            "DriverVersion": "31.0.1",
            "DriverDate": "2025-01-02T00:00:00.0000000Z",
            "AdapterRAM": 1024**3,
            "CurrentHorizontalResolution": 1920,
            "CurrentVerticalResolution": 1080,
            "CurrentRefreshRate": 60,
            "Status": "OK",
            **extra,
        }

    def test_values(self) -> None:
        adapter = (
            GraphicsCollector()
            .collect(context_for({"Win32_VideoController": [self.base()]}))
            .adapters[0]
        )
        assert adapter.memory_bytes.value == 1024**3
        assert adapter.current_width_pixels.value == 1920
        assert adapter.driver_date.value.year == 2025

    def test_saturated_adapter_ram_is_not_presented_as_truth(self) -> None:
        rows = {"Win32_VideoController": [self.base(AdapterRAM=0xFFFFFFFF)]}
        adapter = GraphicsCollector().collect(context_for(rows)).adapters[0]
        assert adapter.memory_bytes.value is None
        assert adapter.memory_bytes.reason == "adapter_ram_saturated_32bit"

    def test_registry_memory_is_preferred(self) -> None:
        registry = FakeRegistry()
        registry.put(
            RegistryHive.LOCAL_MACHINE,
            RegistryView.DEFAULT,
            r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
            {"DriverDesc": "Grafica Ficticia", "HardwareInformation.qwMemorySize": 8 * 1024**3},
        )
        rows = {"Win32_VideoController": [self.base(AdapterRAM=0xFFFFFFFF)]}
        adapter = GraphicsCollector().collect(context_for(rows, registry=registry)).adapters[0]
        assert adapter.memory_bytes.value == 8 * 1024**3

    def test_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            GraphicsCollector().collect(
                context_for({}, {"Win32_VideoController": CimErrorKind.FAILED})
            )


class TestDisplays:
    def test_edid_is_decoded(self) -> None:
        rows = {
            "WmiMonitorID": [
                {
                    "ManufacturerName": [70, 73, 67, 0, 0],
                    "UserFriendlyName": [80, 97, 110, 116, 97, 108, 108, 97, 0],
                    "SerialNumberID": [0, 0],
                    "YearOfManufacture": 2024,
                    "Active": True,
                }
            ]
        }
        section = DisplayCollector().collect(context_for(rows))
        monitor = section.monitors[0]
        assert monitor.manufacturer_code.value == "FIC"
        assert monitor.model.value == "Pantalla"
        assert monitor.serial_number.value is None
        assert section.active_modes[0].width_pixels == 1920

    def test_wmi_failure_keeps_native_modes(self) -> None:
        ctx = context_for({}, {"WmiMonitorID": CimErrorKind.ACCESS_DENIED})
        section = DisplayCollector().collect(ctx)
        assert section.monitors == []
        assert section.active_modes

    def test_total_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            DisplayCollector().collect(
                context_for({}, {"WmiMonitorID": CimErrorKind.FAILED}, native=FakeNative(modes=[]))
            )


class TestNetwork:
    def adapter(self, **extra: Any) -> dict[str, Any]:
        return {
            "Name": "Ethernet",
            "InterfaceDescription": "Controlador Ficticio",
            "DriverProvider": "Fabricante Ficticio",
            "PermanentAddress": "02AABBCCDDEE",
            "MediaConnectState": 1,
            "Speed": 1000000000,
            "DriverVersionString": "1.0.0",
            "HardwareInterface": True,
            "Virtual": False,
            "InterfaceIndex": 7,
            **extra,
        }

    def test_physical_only(self) -> None:
        rows = {
            "MSFT_NetAdapter": [
                self.adapter(),
                self.adapter(Name="VPN Ficticia", HardwareInterface=False, Virtual=True),
            ],
            "Win32_NetworkAdapterConfiguration": [
                {"InterfaceIndex": 7, "IPAddress": ["192.0.2.10", "fe80::1"]}
            ],
        }
        section = NetworkCollector().collect(context_for(rows))
        assert len(section.adapters) == 1
        adapter = section.adapters[0]
        assert adapter.mac_address.value == "02:AA:BB:CC:DD:EE"
        assert adapter.connection.value == "connected"
        assert adapter.ipv4_addresses == ["192.0.2.10"]

    def test_falls_back_to_win32(self) -> None:
        rows = {
            "Win32_NetworkAdapter": [
                {
                    "Name": "Controlador Ficticio",
                    "NetConnectionID": "Ethernet",
                    "Manufacturer": "F",
                    "MACAddress": "02:AA:BB:CC:DD:EE",
                    "NetEnabled": False,
                    "Speed": None,
                    "InterfaceIndex": 1,
                }
            ]
        }
        section = NetworkCollector().collect(
            context_for(rows, {"MSFT_NetAdapter": CimErrorKind.NOT_AVAILABLE})
        )
        assert section.detection_source.endswith("Win32_NetworkAdapter")
        assert section.adapters[0].connection.value == "disconnected"

    def test_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            NetworkCollector().collect(
                context_for(
                    {},
                    {
                        "MSFT_NetAdapter": CimErrorKind.FAILED,
                        "Win32_NetworkAdapter": CimErrorKind.FAILED,
                    },
                )
            )


class TestBattery:
    def test_desktop_without_battery(self) -> None:
        section = BatteryCollector().collect(context_for({}))
        assert section.present is False
        assert section.batteries == []

    def test_health_is_inferred(self) -> None:
        rows = {
            "Win32_Battery": [
                {"Name": "BAT0", "EstimatedChargeRemaining": 80, "BatteryStatus": 2, "Chemistry": 6}
            ],
            "BatteryStaticData": [{"DesignedCapacity": 50000, "ManufactureName": "Ficticia"}],
            "BatteryFullChargedCapacity": [{"FullChargedCapacity": 40000}],
            "BatteryCycleCount": [{"CycleCount": 120}],
        }
        battery = BatteryCollector().collect(context_for(rows)).batteries[0]
        assert battery.health_percent.value == 80
        assert battery.health_percent.confidence is Confidence.INFERRED
        assert battery.chemistry.value == "lithium_ion"
        assert battery.cycle_count.value == 120
        assert battery.status.value == "on_ac_power"

    def test_firmware_without_wmi_details_is_a_warning(self) -> None:
        """Regresión: firmwares sin BatteryStaticData no deben marcar el módulo como fallido."""
        rows = {"Win32_Battery": [{"Name": "BAT0", "EstimatedChargeRemaining": 50}]}
        ctx = context_for(rows, {"BatteryStaticData": CimErrorKind.FAILED})
        battery = BatteryCollector().collect(ctx).batteries[0]
        assert battery.charge_percent.value == 50
        assert battery.design_capacity_mwh.reason == Reason.QUERY_FAILED
        assert battery.health_percent.value is None
        assert ctx.errors == []
        assert ctx.warnings

    def test_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            BatteryCollector().collect(context_for({}, {"Win32_Battery": CimErrorKind.FAILED}))


class TestTpm:
    def test_non_admin_reports_presence_natively(self) -> None:
        ctx = context_for({}, {"Win32_Tpm": CimErrorKind.ACCESS_DENIED})
        section = TpmCollector().collect(ctx)
        assert section.present.value is True
        assert section.spec_version.value == "2.0"
        assert section.manufacturer.reason == Reason.ACCESS_DENIED
        assert ctx.errors == []

    def test_absent(self) -> None:
        section = TpmCollector().collect(
            context_for({}, native=FakeNative(tpm=TpmNativeInfo(False, None)))
        )
        assert section.present.value is False
        assert section.spec_version.reason == Reason.NOT_APPLICABLE

    def test_admin_details(self) -> None:
        rows = {
            "Win32_Tpm": [
                {
                    "SpecVersion": "2.0, 0, 1.38",
                    "ManufacturerIdTxt": "FICT",
                    "ManufacturerVersion": "1.2",
                    "IsEnabled_InitialValue": True,
                    "IsActivated_InitialValue": True,
                }
            ]
        }
        section = TpmCollector().collect(
            context_for(rows, native=FakeNative(tpm=None, elevated=True))
        )
        assert section.spec_version.value == "2.0"
        assert section.manufacturer.value == "FICT"
        assert section.enabled.value is True

    def test_nothing_available(self) -> None:
        section = TpmCollector().collect(
            context_for({}, {"Win32_Tpm": CimErrorKind.ACCESS_DENIED}, native=FakeNative(tpm=None))
        )
        assert section.present.value is None
        assert section.present.reason == Reason.ACCESS_DENIED

    def test_admin_only_class_is_not_queried_without_elevation(self) -> None:
        cim = FakeCim()
        ctx = make_context(make_ports(cim=cim, native=FakeNative(elevated=False)))
        section = TpmCollector().collect(ctx)
        assert "Win32_Tpm" not in cim.calls
        assert section.manufacturer.reason == Reason.ACCESS_DENIED


class TestDevices:
    def test_problems_are_described(self) -> None:
        rows = {
            "Win32_PnPEntity": [
                {
                    "Name": "Dispositivo Ficticio",
                    "PNPClass": "Net",
                    "Manufacturer": "F",
                    "DeviceID": "PCI\\VEN_FFFF",
                    "ConfigManagerErrorCode": 28,
                    "Status": "Error",
                }
            ]
        }
        section = DevicesCollector().collect(context_for(rows))
        assert section.problem_count == 1
        assert section.problems[0].error_code == 28
        assert "controladores" in section.problems[0].error_description.lower()

    def test_unknown_code_has_no_invented_description(self) -> None:
        rows = {"Win32_PnPEntity": [{"Name": "D", "ConfigManagerErrorCode": 99}]}
        assert DevicesCollector().collect(context_for(rows)).problems[0].error_description is None

    def test_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            DevicesCollector().collect(context_for({}, {"Win32_PnPEntity": CimErrorKind.FAILED}))


class TestSecurity:
    def test_full_report(self) -> None:
        registry = FakeRegistry()
        registry.put(
            RegistryHive.LOCAL_MACHINE,
            RegistryView.DEFAULT,
            r"SYSTEM\CurrentControlSet\Control\SecureBoot\State",
            {"UEFISecureBootEnabled": 1},
        )
        registry.put(
            RegistryHive.LOCAL_MACHINE,
            RegistryView.DEFAULT,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
            {"EnableLUA": 1},
        )
        rows = {
            "AntiVirusProduct": [
                {
                    "displayName": "Antivirus Ficticio",
                    "productState": 0x061100,
                    "pathToSignedProductExe": "C:\\AV\\av.exe",
                }
            ],
            "MSFT_MpComputerStatus": [
                {
                    "AntivirusEnabled": True,
                    "RealTimeProtectionEnabled": True,
                    "AMRunningMode": "Normal",
                    "AntivirusSignatureLastUpdated": "2026-11-03T05:00:00.0000000Z",
                }
            ],
            "MSFT_NetFirewallProfile": [
                {"Name": "Domain", "Enabled": 1},
                {"Name": "Public", "Enabled": 2},
            ],
            "Win32_DeviceGuard": [
                {
                    "VirtualizationBasedSecurityStatus": 2,
                    "SecurityServicesRunning": [2],
                    "CodeIntegrityPolicyEnforcementStatus": 2,
                }
            ],
            "Win32_EncryptableVolume": [{"DriveLetter": "C:", "ProtectionStatus": 1}],
        }
        section = SecurityCollector().collect(
            context_for(rows, registry=registry, native=FakeNative(elevated=True))
        )
        assert section.antivirus[0].enabled.value is True
        assert section.antivirus[0].enabled.confidence is Confidence.INFERRED
        assert section.defender.real_time_protection.value is True
        assert section.firewall_profiles[0].enabled.value is True
        assert section.firewall_profiles[1].enabled.value is None
        assert section.secure_boot_enabled.value is True
        assert section.virtualization_based_security.value == "running"
        assert section.memory_integrity_running.value is True
        assert section.code_integrity_policy.value == "enforced"
        assert section.uac_enabled.value is True
        assert section.volume_encryption[0].drive_letter == "C"
        assert section.volume_encryption[0].protection.value == "on"

    def test_each_failure_is_isolated(self) -> None:
        errors = {
            "AntiVirusProduct": CimErrorKind.NOT_AVAILABLE,
            "MSFT_MpComputerStatus": CimErrorKind.FAILED,
            "MSFT_NetFirewallProfile": CimErrorKind.ACCESS_DENIED,
            "Win32_DeviceGuard": CimErrorKind.TRANSIENT,
            "Win32_EncryptableVolume": CimErrorKind.ACCESS_DENIED,
        }
        ctx = context_for(
            {}, errors, registry=FakeRegistry(), powershell=FakePowerShellInfo(mode=None)
        )
        section = SecurityCollector().collect(ctx)
        assert section.antivirus == []
        assert section.antivirus_status.reason == Reason.NOT_AVAILABLE
        assert section.defender is None
        assert section.volume_encryption_status.reason == Reason.ACCESS_DENIED
        assert section.secure_boot_enabled.value is None
        assert section.virtualization_based_security.reason == Reason.QUERY_FAILED
        assert section.powershell_language_mode.value is None
