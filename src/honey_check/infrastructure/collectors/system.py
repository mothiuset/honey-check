"""Módulos de sistema, gráficos, pantallas, red, batería, TPM, dispositivos y seguridad."""

from __future__ import annotations

from typing import Any

from honey_check.application.collection import CollectionContext, ModuleFailed, unknown_from
from honey_check.application.ports import (
    CimQuery,
    CimResult,
    RegistryAccessDenied,
    RegistryHive,
    RegistryKeyMissing,
    RegistryView,
)
from honey_check.domain.classification import (
    DEVICE_ERRORS,
    decode_antivirus_state,
    is_ltsc_edition,
    windows_generation,
)
from honey_check.domain.inventory import (
    Battery,
    BatterySection,
    DefenderStatus,
    DevicesSection,
    DisplayMode,
    DisplaySection,
    FirewallProfile,
    GraphicsAdapter,
    GraphicsSection,
    HotFix,
    Monitor,
    NetworkAdapter,
    NetworkSection,
    OperatingSystem,
    ProblemDevice,
    SecurityProduct,
    SecuritySection,
    TpmSection,
    VolumeEncryption,
)
from honey_check.domain.normalize import (
    clean_text,
    observed_bool,
    observed_datetime,
    observed_positive_int,
    observed_text,
)
from honey_check.domain.observed import Observed, Reason

_ROOT = "root/cimv2"
_WMI = "root/wmi"
_STD = "root/StandardCimv2"


def _read_registry(
    ctx: CollectionContext, path: str, view: RegistryView = RegistryView.DEFAULT
) -> dict[str, Any] | None:
    try:
        return ctx.ports.registry.values(RegistryHive.LOCAL_MACHINE, path, view)
    except (RegistryKeyMissing, RegistryAccessDenied, OSError):
        return None


# --- Sistema operativo ---------------------------------------------------------------------------

_OS = CimQuery(
    _ROOT,
    "Win32_OperatingSystem",
    (
        "Caption",
        "Version",
        "BuildNumber",
        "OSArchitecture",
        "InstallDate",
        "LastBootUpTime",
        "Locale",
    ),
)
_HOTFIX = CimQuery(_ROOT, "Win32_QuickFixEngineering", ("HotFixID", "Description", "InstalledOn"))
_CURRENT_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
_MAX_HOTFIXES = 200
_OSARCH = {"64-bit": "64-bit", "32-bit": "32-bit"}


class OperatingSystemCollector:
    name = "operating_system"
    timeout_s = 60.0

    def collect(self, ctx: CollectionContext) -> OperatingSystem:
        os_r, hotfix_r = ctx.query([_OS, _HOTFIX])
        registry = _read_registry(ctx, _CURRENT_VERSION)
        if not os_r.ok and registry is None:
            raise ModuleFailed(
                "query_failed", "No se pudo consultar el sistema operativo", _OS.source
            )
        row = dict(os_r.rows[0]) if os_r.rows else {}
        reg = registry or {}
        reg_source = f"registry:HKLM\\{_CURRENT_VERSION}"

        build_raw = row.get("BuildNumber") or reg.get("CurrentBuild")
        build = observed_positive_int(build_raw, f"{_OS.source}.BuildNumber")
        ubr = (
            Observed[int].reported(reg["UBR"], f"{reg_source}.UBR")
            if isinstance(reg.get("UBR"), int)
            else Observed[int].unknown(Reason.NOT_REPORTED, f"{reg_source}.UBR")
        )
        edition = observed_text(reg.get("EditionID"), f"{reg_source}.EditionID")
        generation = windows_generation(build.value)
        ltsc = is_ltsc_edition(edition.value)
        display_version = observed_text(
            reg.get("DisplayVersion") or reg.get("ReleaseId"), f"{reg_source}.DisplayVersion"
        )
        hotfixes = [
            HotFix(
                id=text,
                description=clean_text(item.get("Description")),
                installed_on_raw=clean_text(item.get("InstalledOn")),
            )
            for item in hotfix_r.rows[:_MAX_HOTFIXES]
            if (text := clean_text(item.get("HotFixID")))
        ]
        return OperatingSystem(
            # `ProductName` del Registro sigue diciendo «Windows 10» en Windows 11: manda WMI.
            name=(
                observed_text(row.get("Caption"), f"{_OS.source}.Caption")
                if os_r.ok
                else unknown_from(os_r, _OS.source)
            ),
            generation=(
                Observed[str].inferred(generation, "rule:build_number")
                if generation
                else Observed[str].unknown(Reason.NOT_REPORTED, "rule:build_number")
            ),
            edition_id=edition,
            is_ltsc=(
                Observed[bool].inferred(ltsc, "rule:edition_id")
                if ltsc is not None
                else Observed[bool].unknown(Reason.NOT_REPORTED, "rule:edition_id")
            ),
            display_version=display_version,
            version=observed_text(row.get("Version"), f"{_OS.source}.Version"),
            build=build,
            ubr=ubr,
            full_build=(
                Observed[str].inferred(f"{build.value}.{ubr.value}", "rule:build_dot_ubr")
                if build.value is not None and ubr.value is not None
                else Observed[str].unknown(Reason.NOT_REPORTED, "rule:build_dot_ubr")
            ),
            architecture=observed_text(row.get("OSArchitecture"), f"{_OS.source}.OSArchitecture"),
            installed_at=observed_datetime(row.get("InstallDate"), f"{_OS.source}.InstallDate"),
            last_boot_at=observed_datetime(
                row.get("LastBootUpTime"), f"{_OS.source}.LastBootUpTime"
            ),
            locale=observed_text(row.get("Locale"), f"{_OS.source}.Locale"),
            hotfix_count=(
                Observed[int].reported(len(hotfix_r.rows), _HOTFIX.source)
                if hotfix_r.ok
                else unknown_from(hotfix_r, _HOTFIX.source)
            ),
            hotfixes=hotfixes,
        )


# --- Gráficos ------------------------------------------------------------------------------------

_VIDEO = CimQuery(
    _ROOT,
    "Win32_VideoController",
    (
        "Name",
        "AdapterCompatibility",
        "DriverVersion",
        "DriverDate",
        "AdapterRAM",
        "CurrentHorizontalResolution",
        "CurrentVerticalResolution",
        "CurrentRefreshRate",
        "Status",
        "PNPDeviceID",
    ),
)
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_ADAPTER_RAM_32BIT_LIMIT = 0xFFFFFFFF
_MAX_DISPLAY_CLASS_KEYS = 16


class GraphicsCollector:
    name = "graphics"
    timeout_s = 30.0

    def collect(self, ctx: CollectionContext) -> GraphicsSection:
        result = ctx.query([_VIDEO])[0]
        if not result.ok:
            raise ModuleFailed(
                "query_failed", "No se pudieron consultar los gráficos", _VIDEO.source
            )
        memory_by_name = self._registry_memory(ctx)
        adapters = [self._adapter(dict(row), memory_by_name) for row in result.rows]
        return GraphicsSection(adapters=adapters)

    @staticmethod
    def _registry_memory(ctx: CollectionContext) -> dict[str, int]:
        """`qwMemorySize` no sufre el límite de 4 GiB de `AdapterRAM`, que es de 32 bits."""
        found: dict[str, int] = {}
        for index in range(_MAX_DISPLAY_CLASS_KEYS):
            values = _read_registry(ctx, f"{_DISPLAY_CLASS}\\{index:04d}")
            if values is None:
                continue
            name = clean_text(values.get("DriverDesc"))
            size = values.get("HardwareInformation.qwMemorySize")
            if name and isinstance(size, int) and size > 0:
                found[name.lower()] = size
        return found

    @staticmethod
    def _adapter(row: dict[str, Any], memory_by_name: dict[str, int]) -> GraphicsAdapter:
        source = _VIDEO.source
        name = clean_text(row.get("Name"))
        ram = row.get("AdapterRAM")
        registry_memory = memory_by_name.get(name.lower()) if name else None
        memory: Observed[int]
        if registry_memory:
            memory = Observed[int].reported(
                registry_memory, "registry:HardwareInformation.qwMemorySize"
            )
        elif isinstance(ram, int) and 0 < ram < _ADAPTER_RAM_32BIT_LIMIT:
            memory = Observed[int].reported(ram, f"{source}.AdapterRAM")
        elif isinstance(ram, int) and ram >= _ADAPTER_RAM_32BIT_LIMIT:
            memory = Observed[int].unknown(
                "adapter_ram_saturated_32bit", f"{source}.AdapterRAM", raw=str(ram)
            )
        else:
            memory = Observed[int].unknown(Reason.NOT_REPORTED, f"{source}.AdapterRAM")
        return GraphicsAdapter(
            name=observed_text(name, f"{source}.Name"),
            vendor=observed_text(row.get("AdapterCompatibility"), f"{source}.AdapterCompatibility"),
            driver_version=observed_text(row.get("DriverVersion"), f"{source}.DriverVersion"),
            driver_date=observed_datetime(row.get("DriverDate"), f"{source}.DriverDate"),
            memory_bytes=memory,
            current_width_pixels=observed_positive_int(
                row.get("CurrentHorizontalResolution"), f"{source}.CurrentHorizontalResolution"
            ),
            current_height_pixels=observed_positive_int(
                row.get("CurrentVerticalResolution"), f"{source}.CurrentVerticalResolution"
            ),
            current_refresh_hz=observed_positive_int(
                row.get("CurrentRefreshRate"), f"{source}.CurrentRefreshRate"
            ),
            status=observed_text(row.get("Status"), f"{source}.Status"),
        )


# --- Pantallas -----------------------------------------------------------------------------------

_MONITOR = CimQuery(
    _WMI,
    "WmiMonitorID",
    ("ManufacturerName", "UserFriendlyName", "SerialNumberID", "YearOfManufacture", "Active"),
)


def _decode_edid(raw: Any) -> str | None:
    """Los campos EDID llegan como listas de códigos de carácter terminadas en cero."""
    if not isinstance(raw, list):
        return clean_text(raw)
    chars = [chr(c) for c in raw if isinstance(c, int) and 0 < c < 128]
    return clean_text("".join(chars))


class DisplayCollector:
    name = "displays"
    timeout_s = 30.0

    def collect(self, ctx: CollectionContext) -> DisplaySection:
        result = ctx.query([_MONITOR])[0]
        source = _MONITOR.source
        monitors = [
            Monitor(
                manufacturer_code=observed_text(
                    _decode_edid(row.get("ManufacturerName")), f"{source}.ManufacturerName"
                ),
                model=observed_text(
                    _decode_edid(row.get("UserFriendlyName")), f"{source}.UserFriendlyName"
                ),
                serial_number=observed_text(
                    _decode_edid(row.get("SerialNumberID")), f"{source}.SerialNumberID"
                ),
                year_of_manufacture=observed_positive_int(
                    row.get("YearOfManufacture"), f"{source}.YearOfManufacture"
                ),
                is_active=observed_bool(row.get("Active"), f"{source}.Active"),
            )
            for row in result.rows
        ]
        modes = [
            DisplayMode(
                device=mode.device,
                is_primary=mode.is_primary,
                width_pixels=mode.width,
                height_pixels=mode.height,
                refresh_hz=mode.refresh_hz,
            )
            for mode in ctx.ports.native.display_modes()
            if mode.width > 0 and mode.height > 0
        ]
        if not result.ok and not modes:
            raise ModuleFailed("no_data", "No se pudo obtener información de pantallas", source)
        return DisplaySection(monitors=monitors, active_modes=modes)


# --- Red -----------------------------------------------------------------------------------------

_MSFT_ADAPTER = CimQuery(
    _STD,
    "MSFT_NetAdapter",
    (
        "Name",
        "InterfaceDescription",
        "DriverProvider",
        "PermanentAddress",
        "NetworkAddresses",
        "MediaConnectState",
        "Speed",
        "DriverVersionString",
        "HardwareInterface",
        "Virtual",
        "InterfaceIndex",
    ),
)
_WIN32_ADAPTER = CimQuery(
    _ROOT,
    "Win32_NetworkAdapter",
    (
        "Name",
        "NetConnectionID",
        "Manufacturer",
        "MACAddress",
        "NetEnabled",
        "Speed",
        "InterfaceIndex",
    ),
    where="PhysicalAdapter = TRUE",
)
_IP_CONFIG = CimQuery(
    _ROOT,
    "Win32_NetworkAdapterConfiguration",
    ("InterfaceIndex", "IPAddress"),
    where="IPEnabled = TRUE",
)
_MEDIA_STATE = {0: "unknown", 1: "connected", 2: "disconnected"}


def _format_mac(raw: Any) -> str | None:
    text = clean_text(raw)
    if text is None:
        return None
    digits = "".join(ch for ch in text if ch.isalnum()).upper()
    if len(digits) != 12:
        return text
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _ipv4(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else [raw]
    return [str(v) for v in values if isinstance(v, str) and ":" not in v]


class NetworkCollector:
    name = "network"
    timeout_s = 30.0

    def collect(self, ctx: CollectionContext) -> NetworkSection:
        msft_r, ip_r = ctx.query([_MSFT_ADAPTER, _IP_CONFIG])
        ips = {
            row.get("InterfaceIndex"): _ipv4(row.get("IPAddress"))
            for row in ip_r.rows
            if row.get("InterfaceIndex") is not None
        }
        if msft_r.ok:
            physical = [
                dict(row)
                for row in msft_r.rows
                if row.get("HardwareInterface") is True and row.get("Virtual") is not True
            ]
            return NetworkSection(
                adapters=[self._from_msft(row, ips) for row in physical],
                detection_source=_MSFT_ADAPTER.source,
            )
        win32_r = ctx.query([_WIN32_ADAPTER])[0]
        if not win32_r.ok:
            raise ModuleFailed(
                "query_failed", "No se pudieron consultar los adaptadores", _WIN32_ADAPTER.source
            )
        return NetworkSection(
            adapters=[self._from_win32(dict(row), ips) for row in win32_r.rows],
            detection_source=_WIN32_ADAPTER.source,
        )

    @staticmethod
    def _from_msft(row: dict[str, Any], ips: dict[Any, list[str]]) -> NetworkAdapter:
        source = _MSFT_ADAPTER.source
        state = row.get("MediaConnectState")
        state_text = _MEDIA_STATE.get(state) if isinstance(state, int) else None
        mac = _format_mac(row.get("PermanentAddress")) or _format_mac(row.get("NetworkAddresses"))
        return NetworkAdapter(
            name=observed_text(row.get("Name"), f"{source}.Name"),
            description=observed_text(
                row.get("InterfaceDescription"), f"{source}.InterfaceDescription"
            ),
            manufacturer=observed_text(row.get("DriverProvider"), f"{source}.DriverProvider"),
            mac_address=observed_text(mac, f"{source}.PermanentAddress"),
            connection=(
                Observed[str].reported(state_text, f"{source}.MediaConnectState")
                if state_text and state_text != "unknown"
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.MediaConnectState")
            ),
            link_speed_bits_per_second=observed_positive_int(row.get("Speed"), f"{source}.Speed"),
            driver_version=observed_text(
                row.get("DriverVersionString"), f"{source}.DriverVersionString"
            ),
            ipv4_addresses=ips.get(row.get("InterfaceIndex"), []),
        )

    @staticmethod
    def _from_win32(row: dict[str, Any], ips: dict[Any, list[str]]) -> NetworkAdapter:
        source = _WIN32_ADAPTER.source
        enabled = row.get("NetEnabled")
        return NetworkAdapter(
            name=observed_text(row.get("NetConnectionID"), f"{source}.NetConnectionID"),
            description=observed_text(row.get("Name"), f"{source}.Name"),
            manufacturer=observed_text(row.get("Manufacturer"), f"{source}.Manufacturer"),
            mac_address=observed_text(_format_mac(row.get("MACAddress")), f"{source}.MACAddress"),
            connection=(
                Observed[str].reported(
                    "connected" if enabled else "disconnected", f"{source}.NetEnabled"
                )
                if isinstance(enabled, bool)
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.NetEnabled")
            ),
            link_speed_bits_per_second=observed_positive_int(row.get("Speed"), f"{source}.Speed"),
            driver_version=Observed[str].unknown(Reason.NOT_AVAILABLE, source),
            ipv4_addresses=ips.get(row.get("InterfaceIndex"), []),
        )


# --- Batería -------------------------------------------------------------------------------------

_WIN32_BATTERY = CimQuery(
    _ROOT,
    "Win32_Battery",
    (
        "Name",
        "DeviceID",
        "EstimatedChargeRemaining",
        "BatteryStatus",
        "Chemistry",
        "DesignCapacity",
    ),
)
_STATIC_BATTERY = CimQuery(
    _WMI, "BatteryStaticData", ("InstanceName", "DesignedCapacity", "ManufactureName")
)
_FULL_CHARGE = CimQuery(_WMI, "BatteryFullChargedCapacity", ("InstanceName", "FullChargedCapacity"))
_CYCLES = CimQuery(_WMI, "BatteryCycleCount", ("InstanceName", "CycleCount"))
_BATTERY_STATUS = {
    1: "discharging",
    2: "on_ac_power",
    3: "fully_charged",
    4: "low",
    5: "critical",
    6: "charging",
    7: "charging_high",
    8: "charging_low",
    9: "charging_critical",
    10: "undefined",
    11: "partially_charged",
}
_CHEMISTRY = {
    3: "lead_acid",
    4: "nickel_cadmium",
    5: "nickel_metal_hydride",
    6: "lithium_ion",
    7: "zinc_air",
    8: "lithium_polymer",
}


class BatteryCollector:
    name = "battery"
    timeout_s = 30.0

    def collect(self, ctx: CollectionContext) -> BatterySection:
        base_r, static_r, full_r, cycles_r = ctx.query(
            [_WIN32_BATTERY, _STATIC_BATTERY, _FULL_CHARGE, _CYCLES],
            # Muchos firmwares no implementan estas clases: la batería se reporta sin ellas.
            optional=(_STATIC_BATTERY, _FULL_CHARGE, _CYCLES),
        )
        if not base_r.ok:
            raise ModuleFailed(
                "query_failed", "No se pudo consultar la batería", _WIN32_BATTERY.source
            )
        batteries = [
            self._battery(
                dict(row),
                self._nth(static_r, index),
                self._nth(full_r, index),
                self._nth(cycles_r, index),
                static_r,
                full_r,
                cycles_r,
            )
            for index, row in enumerate(base_r.rows)
        ]
        return BatterySection(present=bool(batteries), batteries=batteries)

    @staticmethod
    def _nth(result: CimResult, index: int) -> dict[str, Any]:
        return dict(result.rows[index]) if index < len(result.rows) else {}

    @staticmethod
    def _battery(
        row: dict[str, Any],
        static: dict[str, Any],
        full: dict[str, Any],
        cycles: dict[str, Any],
        static_r: CimResult,
        full_r: CimResult,
        cycles_r: CimResult,
    ) -> Battery:
        source = _WIN32_BATTERY.source
        design = (
            observed_positive_int(
                static.get("DesignedCapacity"), f"{_STATIC_BATTERY.source}.DesignedCapacity"
            )
            if static_r.ok
            else unknown_from(static_r, _STATIC_BATTERY.source)
        )
        if design.value is None and row.get("DesignCapacity"):
            design = observed_positive_int(row.get("DesignCapacity"), f"{source}.DesignCapacity")
        full_charge = (
            observed_positive_int(
                full.get("FullChargedCapacity"), f"{_FULL_CHARGE.source}.FullChargedCapacity"
            )
            if full_r.ok
            else unknown_from(full_r, _FULL_CHARGE.source)
        )
        health = (
            Observed[int].inferred(
                round(full_charge.value * 100 / design.value), "rule:full_charge_over_design"
            )
            if full_charge.value is not None and design.value
            else Observed[int].unknown(Reason.NOT_REPORTED, "rule:full_charge_over_design")
        )
        status_code = row.get("BatteryStatus")
        status_text = _BATTERY_STATUS.get(status_code) if isinstance(status_code, int) else None
        chemistry_code = row.get("Chemistry")
        chemistry = _CHEMISTRY.get(chemistry_code) if isinstance(chemistry_code, int) else None
        charge = row.get("EstimatedChargeRemaining")
        return Battery(
            name=observed_text(row.get("Name"), f"{source}.Name"),
            manufacturer=(
                observed_text(
                    static.get("ManufactureName"), f"{_STATIC_BATTERY.source}.ManufactureName"
                )
                if static_r.ok
                else unknown_from(static_r, _STATIC_BATTERY.source)
            ),
            chemistry=(
                Observed[str].reported(chemistry, f"{source}.Chemistry")
                if chemistry
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.Chemistry")
            ),
            charge_percent=(
                Observed[int].reported(charge, f"{source}.EstimatedChargeRemaining")
                if isinstance(charge, int) and 0 <= charge <= 100
                else Observed[int].unknown(
                    Reason.NOT_REPORTED, f"{source}.EstimatedChargeRemaining"
                )
            ),
            status=(
                Observed[str].reported(status_text, f"{source}.BatteryStatus")
                if status_text
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.BatteryStatus")
            ),
            design_capacity_mwh=design,
            full_charge_capacity_mwh=full_charge,
            health_percent=health,
            cycle_count=(
                observed_positive_int(cycles.get("CycleCount"), f"{_CYCLES.source}.CycleCount")
                if cycles_r.ok
                else unknown_from(cycles_r, _CYCLES.source)
            ),
        )


# --- TPM -----------------------------------------------------------------------------------------

_TPM = CimQuery(
    "root/cimv2/Security/MicrosoftTpm",
    "Win32_Tpm",
    (
        "SpecVersion",
        "ManufacturerIdTxt",
        "ManufacturerVersion",
        "IsEnabled_InitialValue",
        "IsActivated_InitialValue",
    ),
)


class TpmCollector:
    name = "tpm"
    timeout_s = 30.0

    def collect(self, ctx: CollectionContext) -> TpmSection:
        native = ctx.ports.native.tpm_info()
        result = ctx.query([_TPM], admin_only=(_TPM,))[0]
        source = _TPM.source
        row = dict(result.rows[0]) if result.rows else {}
        spec_raw = clean_text(row.get("SpecVersion"))

        def detail(name: str) -> Observed[str]:
            if not result.ok:
                return unknown_from(result, source)
            return observed_text(row.get(name), f"{source}.{name}")

        def flag(name: str) -> Observed[bool]:
            if not result.ok:
                return unknown_from(result, source)
            return observed_bool(row.get(name), f"{source}.{name}")

        present: Observed[bool]
        if native is not None:
            present = Observed[bool].reported(native.present, "native:Tbsi_GetDeviceInfo")
        elif result.ok:
            present = Observed[bool].reported(bool(result.rows), source)
        else:
            present = unknown_from(result, source)

        spec: Observed[str]
        if native is not None and native.spec_version:
            spec = Observed[str].reported(native.spec_version, "native:Tbsi_GetDeviceInfo")
        elif spec_raw:
            spec = Observed[str].reported(spec_raw.split(",")[0].strip(), f"{source}.SpecVersion")
        elif native is not None and not native.present:
            spec = Observed[str].unknown(Reason.NOT_APPLICABLE, source)
        else:
            spec = detail("SpecVersion")

        return TpmSection(
            present=present,
            spec_version=spec,
            manufacturer=detail("ManufacturerIdTxt"),
            firmware_version=detail("ManufacturerVersion"),
            enabled=flag("IsEnabled_InitialValue"),
            activated=flag("IsActivated_InitialValue"),
        )


# --- Dispositivos --------------------------------------------------------------------------------

_PNP_COUNT = CimQuery(_ROOT, "Win32_PnPEntity", ("ConfigManagerErrorCode",))
_PNP_PROBLEMS = CimQuery(
    _ROOT,
    "Win32_PnPEntity",
    ("Name", "PNPClass", "Manufacturer", "DeviceID", "ConfigManagerErrorCode", "Status"),
    where="ConfigManagerErrorCode <> 0",
)


class DevicesCollector:
    name = "devices"
    timeout_s = 45.0

    def collect(self, ctx: CollectionContext) -> DevicesSection:
        total_r, problems_r = ctx.query([_PNP_COUNT, _PNP_PROBLEMS])
        if not problems_r.ok:
            raise ModuleFailed(
                "query_failed",
                "No se pudo consultar el estado de dispositivos",
                _PNP_PROBLEMS.source,
            )
        source = _PNP_PROBLEMS.source
        problems = [
            ProblemDevice(
                name=observed_text(row.get("Name"), f"{source}.Name"),
                device_class=observed_text(row.get("PNPClass"), f"{source}.PNPClass"),
                manufacturer=observed_text(row.get("Manufacturer"), f"{source}.Manufacturer"),
                device_id=clean_text(row.get("DeviceID")),
                error_code=int(row.get("ConfigManagerErrorCode") or 0),
                error_description=DEVICE_ERRORS.get(int(row.get("ConfigManagerErrorCode") or 0)),
                status=observed_text(row.get("Status"), f"{source}.Status"),
            )
            for row in problems_r.rows
        ]
        return DevicesSection(
            total_count=(
                Observed[int].reported(len(total_r.rows), _PNP_COUNT.source)
                if total_r.ok
                else unknown_from(total_r, _PNP_COUNT.source)
            ),
            problem_count=len(problems),
            problems=problems,
        )


# --- Seguridad -----------------------------------------------------------------------------------

_ANTIVIRUS = CimQuery(
    "root/SecurityCenter2",
    "AntiVirusProduct",
    ("displayName", "productState", "pathToSignedProductExe"),
)
_DEFENDER = CimQuery(
    "root/Microsoft/Windows/Defender",
    "MSFT_MpComputerStatus",
    (
        "AntivirusEnabled",
        "RealTimeProtectionEnabled",
        "AMRunningMode",
        "AntivirusSignatureLastUpdated",
    ),
)
_FIREWALL = CimQuery(_STD, "MSFT_NetFirewallProfile", ("Name", "Enabled"))
_DEVICE_GUARD = CimQuery(
    "root/Microsoft/Windows/DeviceGuard",
    "Win32_DeviceGuard",
    (
        "VirtualizationBasedSecurityStatus",
        "SecurityServicesRunning",
        "CodeIntegrityPolicyEnforcementStatus",
    ),
)
_BITLOCKER = CimQuery(
    "root/cimv2/Security/MicrosoftVolumeEncryption",
    "Win32_EncryptableVolume",
    ("DriveLetter", "ProtectionStatus"),
)
_VBS_STATUS = {0: "disabled", 1: "enabled_not_running", 2: "running"}
_CODE_INTEGRITY = {0: "off", 1: "audit", 2: "enforced"}
_HVCI_SERVICE = 2  # SecurityServicesRunning: 2 = integridad de memoria (HVCI)
_PROTECTION = {0: "off", 1: "on", 2: "unknown"}
_FIREWALL_ENABLED = {0: False, 1: True}


class SecurityCollector:
    name = "security"
    timeout_s = 60.0

    def collect(self, ctx: CollectionContext) -> SecuritySection:
        av_r, defender_r, firewall_r, guard_r, bitlocker_r = ctx.query(
            [_ANTIVIRUS, _DEFENDER, _FIREWALL, _DEVICE_GUARD, _BITLOCKER],
            admin_only=(_BITLOCKER,),
        )
        guard = dict(guard_r.rows[0]) if guard_r.rows else {}

        vbs_code = guard.get("VirtualizationBasedSecurityStatus")
        vbs = _VBS_STATUS.get(vbs_code) if isinstance(vbs_code, int) else None
        ci_code = guard.get("CodeIntegrityPolicyEnforcementStatus")
        ci = _CODE_INTEGRITY.get(ci_code) if isinstance(ci_code, int) else None
        running = guard.get("SecurityServicesRunning")
        guard_source = _DEVICE_GUARD.source

        language = ctx.ports.powershell.language_mode(ctx.cancel, 30.0)
        volumes = [
            VolumeEncryption(
                drive_letter=letter[0].upper(),
                protection=(
                    Observed[str].reported(protection, f"{_BITLOCKER.source}.ProtectionStatus")
                    if protection and protection != "unknown"
                    else Observed[str].unknown(
                        Reason.NOT_REPORTED, f"{_BITLOCKER.source}.ProtectionStatus"
                    )
                ),
            )
            for row in bitlocker_r.rows
            if (letter := clean_text(row.get("DriveLetter")))
            for protection in [
                _PROTECTION.get(row.get("ProtectionStatus"))  # type: ignore[arg-type]
                if isinstance(row.get("ProtectionStatus"), int)
                else None
            ]
        ]
        return SecuritySection(
            antivirus=[self._antivirus(dict(row)) for row in av_r.rows],
            antivirus_status=self._query_status(av_r, _ANTIVIRUS),
            defender=self._defender(dict(defender_r.rows[0])) if defender_r.rows else None,
            firewall_profiles=[
                FirewallProfile(
                    name=clean_text(row.get("Name")) or "?",
                    enabled=self._firewall_enabled(row.get("Enabled")),
                )
                for row in firewall_r.rows
            ],
            secure_boot_enabled=self._secure_boot(ctx),
            virtualization_based_security=(
                Observed[str].reported(vbs, f"{guard_source}.VirtualizationBasedSecurityStatus")
                if vbs
                else (
                    unknown_from(guard_r, guard_source)
                    if not guard_r.ok
                    else Observed[str].unknown(Reason.NOT_REPORTED, guard_source)
                )
            ),
            memory_integrity_running=(
                Observed[bool].reported(
                    _HVCI_SERVICE in running, f"{guard_source}.SecurityServicesRunning"
                )
                if isinstance(running, list)
                else (
                    Observed[bool].reported(
                        running == _HVCI_SERVICE, f"{guard_source}.SecurityServicesRunning"
                    )
                    if isinstance(running, int)
                    else (
                        unknown_from(guard_r, guard_source)
                        if not guard_r.ok
                        else Observed[bool].unknown(Reason.NOT_REPORTED, guard_source)
                    )
                )
            ),
            code_integrity_policy=(
                Observed[str].reported(ci, f"{guard_source}.CodeIntegrityPolicyEnforcementStatus")
                if ci
                else (
                    unknown_from(guard_r, guard_source)
                    if not guard_r.ok
                    else Observed[str].unknown(Reason.NOT_REPORTED, guard_source)
                )
            ),
            uac_enabled=self._uac(ctx),
            powershell_language_mode=(
                Observed[str].reported(language, "powershell:LanguageMode")
                if language
                else Observed[str].unknown(Reason.QUERY_FAILED, "powershell:LanguageMode")
            ),
            volume_encryption=volumes,
            volume_encryption_status=self._query_status(bitlocker_r, _BITLOCKER),
        )

    @staticmethod
    def _query_status(result: CimResult, query: CimQuery) -> Observed[str]:
        if result.ok:
            return Observed[str].reported("queried", query.source)
        return unknown_from(result, query.source)

    @staticmethod
    def _firewall_enabled(raw: Any) -> Observed[bool]:
        source = f"{_FIREWALL.source}.Enabled"
        enabled = _FIREWALL_ENABLED.get(raw) if isinstance(raw, int) else None
        if enabled is None:
            # 2 significa «no configurado»: el efecto real depende de la directiva.
            return Observed[bool].unknown(Reason.NOT_REPORTED, source, raw=str(raw))
        return Observed[bool].reported(enabled, source)

    @staticmethod
    def _antivirus(row: dict[str, Any]) -> SecurityProduct:
        source = _ANTIVIRUS.source
        state = row.get("productState")
        enabled, current = decode_antivirus_state(state if isinstance(state, int) else None)
        rule = "rule:security_center_product_state"
        return SecurityProduct(
            name=observed_text(row.get("displayName"), f"{source}.displayName"),
            enabled=(
                Observed[bool].inferred(enabled, rule)
                if enabled is not None
                else Observed[bool].unknown(Reason.NOT_REPORTED, rule)
            ),
            up_to_date=(
                Observed[bool].inferred(current, rule)
                if current is not None
                else Observed[bool].unknown(Reason.NOT_REPORTED, rule)
            ),
            executable_path=observed_text(
                row.get("pathToSignedProductExe"), f"{source}.pathToSignedProductExe"
            ),
        )

    @staticmethod
    def _defender(row: dict[str, Any]) -> DefenderStatus:
        source = _DEFENDER.source
        return DefenderStatus(
            antivirus_enabled=observed_bool(
                row.get("AntivirusEnabled"), f"{source}.AntivirusEnabled"
            ),
            real_time_protection=observed_bool(
                row.get("RealTimeProtectionEnabled"), f"{source}.RealTimeProtectionEnabled"
            ),
            running_mode=observed_text(row.get("AMRunningMode"), f"{source}.AMRunningMode"),
            signature_updated_at=observed_datetime(
                row.get("AntivirusSignatureLastUpdated"), f"{source}.AntivirusSignatureLastUpdated"
            ),
        )

    @staticmethod
    def _secure_boot(ctx: CollectionContext) -> Observed[bool]:
        path = r"SYSTEM\CurrentControlSet\Control\SecureBoot\State"
        source = f"registry:HKLM\\{path}.UEFISecureBootEnabled"
        values = _read_registry(ctx, path)
        if values is None:
            # La clave no existe en firmware BIOS heredado o en equipos sin Secure Boot.
            return Observed[bool].unknown(Reason.NOT_AVAILABLE, source)
        raw = values.get("UEFISecureBootEnabled")
        if isinstance(raw, int):
            return Observed[bool].reported(raw == 1, source)
        return Observed[bool].unknown(Reason.NOT_REPORTED, source)

    @staticmethod
    def _uac(ctx: CollectionContext) -> Observed[bool]:
        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
        source = f"registry:HKLM\\{path}.EnableLUA"
        values = _read_registry(ctx, path)
        raw = values.get("EnableLUA") if values else None
        if isinstance(raw, int):
            return Observed[bool].reported(raw == 1, source)
        return Observed[bool].unknown(Reason.NOT_REPORTED, source)
