"""Módulos de identificación, procesador, memoria y almacenamiento."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from honey_check.application.collection import CollectionContext, ModuleFailed, unknown_from
from honey_check.application.ports import CimQuery, CimResult
from honey_check.domain.classification import (
    BUS_BY_CODE,
    EXTERNAL_REASONS,
    DeviceType,
    DiskBus,
    DiskKind,
    classify_disk,
    controller_vendor,
    device_type,
    disk_vendor,
    exclusion_reason,
    memory_form_factor,
    memory_type_from_smbios,
    pnp_says_usb,
)
from honey_check.domain.inventory import (
    Baseboard,
    DeviceIdentity,
    DomainMembership,
    ExcludedDisk,
    Firmware,
    MemoryModule,
    MemorySection,
    Partition,
    PhysicalDisk,
    Processor,
    ProcessorSection,
    StorageSection,
    Volume,
)
from honey_check.domain.normalize import (
    clean_text,
    observed_bool,
    observed_positive_int,
    observed_text,
    parse_iso_datetime,
)
from honey_check.domain.observed import Observed, Reason

_ROOT = "root/cimv2"
_STORAGE = "root/Microsoft/Windows/Storage"

_COMPUTER_SYSTEM = CimQuery(
    _ROOT,
    "Win32_ComputerSystem",
    (
        "Name",
        "Manufacturer",
        "Model",
        "SystemSKUNumber",
        "SystemType",
        "PCSystemType",
        "PCSystemTypeEx",
        "Domain",
        "PartOfDomain",
        "Workgroup",
    ),
)
_PRODUCT = CimQuery(_ROOT, "Win32_ComputerSystemProduct", ("IdentifyingNumber", "UUID"))
_BIOS = CimQuery(
    _ROOT,
    "Win32_BIOS",
    (
        "Manufacturer",
        "SMBIOSBIOSVersion",
        "SMBIOSMajorVersion",
        "SMBIOSMinorVersion",
        "ReleaseDate",
        "SerialNumber",
    ),
)
_BOARD = CimQuery(_ROOT, "Win32_BaseBoard", ("Manufacturer", "Product", "SerialNumber", "Version"))
_ENCLOSURE = CimQuery(_ROOT, "Win32_SystemEnclosure", ("ChassisTypes", "SMBIOSAssetTag"))


def _first(result: CimResult) -> dict[str, Any]:
    return dict(result.rows[0]) if result.rows else {}


def _text_or_unknown(
    result: CimResult, row: dict[str, Any], name: str, source: str
) -> Observed[str]:
    if not result.ok:
        return unknown_from(result, source)
    return observed_text(row.get(name), f"{source}.{name}")


def _int_list(raw: Any) -> list[int]:
    items = raw if isinstance(raw, list) else [raw]
    return [int(item) for item in items if isinstance(item, int) and not isinstance(item, bool)]


class IdentityCollector:
    name = "identity"
    timeout_s = 45.0

    def collect(self, ctx: CollectionContext) -> DeviceIdentity:
        system_r, product_r, bios_r, board_r, enclosure_r = ctx.query(
            [_COMPUTER_SYSTEM, _PRODUCT, _BIOS, _BOARD, _ENCLOSURE]
        )
        if not any(r.ok for r in (system_r, product_r, bios_r, board_r, enclosure_r)):
            raise ModuleFailed("all_queries_failed", "Ninguna consulta de identificación respondió")
        system, product, bios = _first(system_r), _first(product_r), _first(bios_r)
        board, enclosure = _first(board_r), _first(enclosure_r)

        cs, ps = _COMPUTER_SYSTEM.source, _PRODUCT.source
        bb, en = _BOARD.source, _ENCLOSURE.source

        native_name = ctx.ports.native.computer_name()
        hostname = (
            Observed[str].reported(native_name, "native:GetComputerNameExW")
            if native_name
            else _text_or_unknown(system_r, system, "Name", cs)
        )
        return DeviceIdentity(
            hostname=hostname,
            manufacturer=_text_or_unknown(system_r, system, "Manufacturer", cs),
            model=_text_or_unknown(system_r, system, "Model", cs),
            serial_number=self._serial(bios_r, bios, product_r, product),
            system_uuid=_text_or_unknown(product_r, product, "UUID", ps),
            sku=_text_or_unknown(system_r, system, "SystemSKUNumber", cs),
            asset_tag=_text_or_unknown(enclosure_r, enclosure, "SMBIOSAssetTag", en),
            device_type=self._device_type(system_r, system, enclosure),
            system_architecture=self._architecture(ctx, system_r, system),
            baseboard=Baseboard(
                manufacturer=_text_or_unknown(board_r, board, "Manufacturer", bb),
                product=_text_or_unknown(board_r, board, "Product", bb),
                serial_number=_text_or_unknown(board_r, board, "SerialNumber", bb),
                version=_text_or_unknown(board_r, board, "Version", bb),
            ),
            firmware=self._firmware(ctx, bios_r, bios),
            membership=self._membership(system_r, system),
        )

    @staticmethod
    def _serial(
        bios_r: CimResult, bios: dict[str, Any], product_r: CimResult, product: dict[str, Any]
    ) -> Observed[str]:
        from_bios = _text_or_unknown(bios_r, bios, "SerialNumber", _BIOS.source)
        if from_bios.value is not None:
            return from_bios
        from_product = _text_or_unknown(product_r, product, "IdentifyingNumber", _PRODUCT.source)
        return from_product if from_product.value is not None else from_bios

    @staticmethod
    def _device_type(
        system_r: CimResult, system: dict[str, Any], enclosure: dict[str, Any]
    ) -> Observed[DeviceType]:
        pc_type = system.get("PCSystemTypeEx") or system.get("PCSystemType")
        kind, rule = device_type(
            _int_list(enclosure.get("ChassisTypes")),
            pc_type if isinstance(pc_type, int) else None,
            clean_text(system.get("Model")),
        )
        if kind is None or rule is None:
            if not system_r.ok:
                return unknown_from(system_r, _COMPUTER_SYSTEM.source)
            return Observed[DeviceType].unknown(Reason.NOT_REPORTED, _ENCLOSURE.source)
        return Observed[DeviceType].inferred(kind, f"rule:{rule}")

    @staticmethod
    def _architecture(
        ctx: CollectionContext, system_r: CimResult, system: dict[str, Any]
    ) -> Observed[str]:
        native = ctx.ports.native.native_architecture()
        if native:
            return Observed[str].reported(native, "native:IsWow64Process2")
        return _text_or_unknown(system_r, system, "SystemType", _COMPUTER_SYSTEM.source)

    @staticmethod
    def _firmware(ctx: CollectionContext, bios_r: CimResult, bios: dict[str, Any]) -> Firmware:
        source = _BIOS.source
        major, minor = bios.get("SMBIOSMajorVersion"), bios.get("SMBIOSMinorVersion")
        smbios = (
            Observed[str].reported(f"{major}.{minor}", f"{source}.SMBIOSMajorVersion")
            if isinstance(major, int) and isinstance(minor, int) and major > 0
            else (
                unknown_from(bios_r, source)
                if not bios_r.ok
                else Observed[str].unknown(Reason.NOT_REPORTED, source)
            )
        )
        release = parse_iso_datetime(bios.get("ReleaseDate"))
        mode = ctx.ports.native.firmware_mode()
        return Firmware(
            vendor=_text_or_unknown(bios_r, bios, "Manufacturer", source),
            version=_text_or_unknown(bios_r, bios, "SMBIOSBIOSVersion", source),
            smbios_version=smbios,
            release_date=(
                Observed[str].reported(release.date().isoformat(), f"{source}.ReleaseDate")
                if release
                else (
                    unknown_from(bios_r, source)
                    if not bios_r.ok
                    else Observed[str].unknown(Reason.NOT_REPORTED, source)
                )
            ),
            mode=(
                Observed[str].reported(mode, "native:GetFirmwareType")
                if mode
                else Observed[str].unknown(Reason.NOT_REPORTED, "native:GetFirmwareType")
            ),
        )

    @staticmethod
    def _membership(system_r: CimResult, system: dict[str, Any]) -> DomainMembership:
        source = _COMPUTER_SYSTEM.source
        part_of_domain = system.get("PartOfDomain")
        if not isinstance(part_of_domain, bool):
            unknown: Observed[str] = (
                unknown_from(system_r, source)
                if not system_r.ok
                else Observed[str].unknown(Reason.NOT_REPORTED, source)
            )
            return DomainMembership(kind=unknown, name=unknown)
        if part_of_domain:
            return DomainMembership(
                kind=Observed[str].reported("domain", f"{source}.PartOfDomain"),
                name=observed_text(system.get("Domain"), f"{source}.Domain"),
            )
        return DomainMembership(
            kind=Observed[str].reported("workgroup", f"{source}.PartOfDomain"),
            name=observed_text(
                system.get("Workgroup") or system.get("Domain"), f"{source}.Workgroup"
            ),
        )


_PROCESSOR = CimQuery(
    _ROOT,
    "Win32_Processor",
    (
        "Name",
        "Manufacturer",
        "Architecture",
        "NumberOfCores",
        "NumberOfLogicalProcessors",
        "MaxClockSpeed",
        "SocketDesignation",
        "AddressWidth",
        "L2CacheSize",
        "L3CacheSize",
        "VirtualizationFirmwareEnabled",
    ),
)
_CPU_ARCHITECTURES = {0: "x86", 5: "arm", 9: "x64", 12: "arm64"}


class ProcessorCollector:
    name = "processor"
    timeout_s = 30.0

    def collect(self, ctx: CollectionContext) -> ProcessorSection:
        result = ctx.query([_PROCESSOR])[0]
        if not result.ok:
            raise ModuleFailed(
                "query_failed", "No se pudo consultar el procesador", _PROCESSOR.source
            )
        if not result.rows:
            raise ModuleFailed("no_data", "Windows no reportó ningún procesador", _PROCESSOR.source)
        processors = [self._processor(dict(row)) for row in result.rows]
        return ProcessorSection(
            processors=processors,
            total_physical_cores=self._sum([p.physical_cores for p in processors]),
            total_logical_processors=self._sum([p.logical_processors for p in processors]),
        )

    @staticmethod
    def _sum(values: list[Observed[int]]) -> Observed[int]:
        if any(v.value is None for v in values):
            return Observed[int].unknown(Reason.NOT_REPORTED, _PROCESSOR.source)
        return Observed[int].inferred(sum(v.value or 0 for v in values), f"sum:{_PROCESSOR.source}")

    @staticmethod
    def _processor(row: dict[str, Any]) -> Processor:
        source = _PROCESSOR.source
        architecture_code = row.get("Architecture")
        architecture = (
            _CPU_ARCHITECTURES.get(architecture_code)
            if isinstance(architecture_code, int)
            else None
        )
        return Processor(
            manufacturer=observed_text(row.get("Manufacturer"), f"{source}.Manufacturer"),
            model=observed_text(row.get("Name"), f"{source}.Name"),
            architecture=(
                Observed[str].reported(architecture, f"{source}.Architecture")
                if architecture
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.Architecture")
            ),
            physical_cores=observed_positive_int(
                row.get("NumberOfCores"), f"{source}.NumberOfCores"
            ),
            logical_processors=observed_positive_int(
                row.get("NumberOfLogicalProcessors"), f"{source}.NumberOfLogicalProcessors"
            ),
            max_frequency_mhz=observed_positive_int(
                row.get("MaxClockSpeed"), f"{source}.MaxClockSpeed"
            ),
            socket=observed_text(row.get("SocketDesignation"), f"{source}.SocketDesignation"),
            address_width_bits=observed_positive_int(
                row.get("AddressWidth"), f"{source}.AddressWidth"
            ),
            l2_cache_kib=observed_positive_int(row.get("L2CacheSize"), f"{source}.L2CacheSize"),
            l3_cache_kib=observed_positive_int(row.get("L3CacheSize"), f"{source}.L3CacheSize"),
            virtualization_firmware_enabled=observed_bool(
                row.get("VirtualizationFirmwareEnabled"), f"{source}.VirtualizationFirmwareEnabled"
            ),
        )


_PHYSICAL_MEMORY = CimQuery(
    _ROOT,
    "Win32_PhysicalMemory",
    (
        "Capacity",
        "SMBIOSMemoryType",
        "MemoryType",
        "Speed",
        "ConfiguredClockSpeed",
        "Manufacturer",
        "PartNumber",
        "SerialNumber",
        "DeviceLocator",
        "BankLabel",
        "FormFactor",
    ),
)
_MEMORY_ARRAY = CimQuery(_ROOT, "Win32_PhysicalMemoryArray", ("MemoryDevices", "Use"))
_MEMORY_TOTAL = CimQuery(_ROOT, "Win32_ComputerSystem", ("TotalPhysicalMemory",))
_SYSTEM_MEMORY_USE = 3  # Win32_PhysicalMemoryArray.Use: memoria del sistema


class MemoryCollector:
    name = "memory"
    timeout_s = 30.0

    def collect(self, ctx: CollectionContext) -> MemorySection:
        modules_r, arrays_r, total_r = ctx.query([_PHYSICAL_MEMORY, _MEMORY_ARRAY, _MEMORY_TOTAL])
        if not modules_r.ok and not total_r.ok:
            raise ModuleFailed(
                "query_failed", "No se pudo consultar la memoria", _PHYSICAL_MEMORY.source
            )
        modules = [self._module(dict(row)) for row in modules_r.rows]
        if modules_r.ok and not modules:
            ctx.warn("no_modules", "SMBIOS no reportó módulos de memoria", _PHYSICAL_MEMORY.source)

        total_slots = self._total_slots(arrays_r)
        return MemorySection(
            installed_bytes=self._installed(modules_r, modules),
            visible_to_os_bytes=(
                observed_positive_int(
                    _first(total_r).get("TotalPhysicalMemory"),
                    f"{_MEMORY_TOTAL.source}.TotalPhysicalMemory",
                )
                if total_r.ok
                else unknown_from(total_r, _MEMORY_TOTAL.source)
            ),
            module_count=len(modules),
            modules=modules,
            total_slots=total_slots,
            free_slots=self._free_slots(ctx, modules_r, total_slots, len(modules)),
        )

    @staticmethod
    def _installed(result: CimResult, modules: list[MemoryModule]) -> Observed[int]:
        source = _PHYSICAL_MEMORY.source
        if not result.ok:
            return unknown_from(result, source)
        if not modules or any(m.capacity_bytes.value is None for m in modules):
            return Observed[int].unknown(Reason.NOT_REPORTED, source)
        return Observed[int].inferred(
            sum(m.capacity_bytes.value or 0 for m in modules), f"sum:{source}.Capacity"
        )

    @staticmethod
    def _total_slots(result: CimResult) -> Observed[int]:
        source = f"{_MEMORY_ARRAY.source}.MemoryDevices"
        if not result.ok:
            return unknown_from(result, _MEMORY_ARRAY.source)
        rows = [r for r in result.rows if r.get("Use") in (_SYSTEM_MEMORY_USE, None)] or list(
            result.rows
        )
        counts = [r.get("MemoryDevices") for r in rows]
        if not counts or any(not isinstance(c, int) or c <= 0 for c in counts):
            return Observed[int].unknown(Reason.NOT_REPORTED, source)
        return Observed[int].reported(sum(c for c in counts if isinstance(c, int)), source)

    @staticmethod
    def _free_slots(
        ctx: CollectionContext, modules_r: CimResult, total: Observed[int], used: int
    ) -> Observed[int]:
        source = "rule:slots_reported_minus_modules"
        if not modules_r.ok or total.value is None:
            return Observed[int].unknown(Reason.NOT_REPORTED, source)
        if used > total.value:
            # SMBIOS contradictorio: hay más módulos que ranuras. No se publica un número falso.
            ctx.warn(
                "inconsistent_memory_slots",
                "SMBIOS reporta menos ranuras que módulos instalados",
                _MEMORY_ARRAY.source,
            )
            return Observed[int].unknown(Reason.INVALID_VALUE, source)
        return Observed[int].inferred(total.value - used, source)

    @staticmethod
    def _module(row: dict[str, Any]) -> MemoryModule:
        source = _PHYSICAL_MEMORY.source
        smbios_code = row.get("SMBIOSMemoryType")
        legacy_code = row.get("MemoryType")
        memory_type: Observed[str]
        name = memory_type_from_smbios(smbios_code if isinstance(smbios_code, int) else None)
        if name:
            memory_type = Observed[str].reported(name, f"{source}.SMBIOSMemoryType")
        else:
            legacy = memory_type_from_smbios(legacy_code if isinstance(legacy_code, int) else None)
            memory_type = (
                Observed[str].reported(legacy, f"{source}.MemoryType")
                if legacy
                else Observed[str].unknown(
                    Reason.NOT_REPORTED, f"{source}.SMBIOSMemoryType", raw=str(smbios_code)
                )
            )
        factor = memory_form_factor(
            row.get("FormFactor") if isinstance(row.get("FormFactor"), int) else None
        )
        return MemoryModule(
            capacity_bytes=observed_positive_int(row.get("Capacity"), f"{source}.Capacity"),
            memory_type=memory_type,
            speed_mts=observed_positive_int(row.get("Speed"), f"{source}.Speed"),
            configured_speed_mts=observed_positive_int(
                row.get("ConfiguredClockSpeed"), f"{source}.ConfiguredClockSpeed"
            ),
            manufacturer=observed_text(row.get("Manufacturer"), f"{source}.Manufacturer"),
            part_number=observed_text(row.get("PartNumber"), f"{source}.PartNumber"),
            serial_number=observed_text(row.get("SerialNumber"), f"{source}.SerialNumber"),
            slot=observed_text(row.get("DeviceLocator"), f"{source}.DeviceLocator"),
            bank=observed_text(row.get("BankLabel"), f"{source}.BankLabel"),
            form_factor=(
                Observed[str].reported(factor, f"{source}.FormFactor")
                if factor
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.FormFactor")
            ),
        )


_MSFT_PHYSICAL = CimQuery(
    _STORAGE,
    "MSFT_PhysicalDisk",
    (
        "DeviceId",
        "FriendlyName",
        "Manufacturer",
        "Model",
        "SerialNumber",
        "Size",
        "BusType",
        "MediaType",
        "SpindleSpeed",
        "HealthStatus",
    ),
)
_MSFT_DISK = CimQuery(_STORAGE, "MSFT_Disk", ("Number", "IsBoot", "IsSystem", "BusType"))
_MSFT_PARTITION = CimQuery(
    _STORAGE,
    "MSFT_Partition",
    ("DiskNumber", "PartitionNumber", "DriveLetter", "Size", "GptType", "MbrType", "AccessPaths"),
)
_MSFT_VOLUME = CimQuery(
    _STORAGE,
    "MSFT_Volume",
    ("Path", "DriveLetter", "FileSystemLabel", "FileSystem", "Size", "SizeRemaining"),
)
_WIN32_DISK = CimQuery(
    _ROOT,
    "Win32_DiskDrive",
    (
        "Index",
        "Model",
        "Manufacturer",
        "SerialNumber",
        "Size",
        "InterfaceType",
        "PNPDeviceID",
        "MediaType",
    ),
)
_CONTROLLER_CLASSES = ("DiskDrive", "SCSIAdapter", "HDC")
_HEALTH = {0: "healthy", 1: "warning", 2: "unhealthy", 5: "unknown"}
_GPT_KINDS = {
    "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}": "efi_system",
    "{e3c9e316-0b5c-4db8-817d-f92df00215ae}": "microsoft_reserved",
    "{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}": "basic_data",
    "{de94bba4-06d1-4d40-a16a-bfd50179d6ac}": "recovery",
}
_WIN32_BUS = {
    "IDE": DiskBus.ATA,
    "SCSI": DiskBus.SCSI,
    "USB": DiskBus.USB,
    "1394": DiskBus.FIREWIRE,
}


def _letter(raw: Any) -> str | None:
    # DriveLetter es un carácter de 16 bits: por COM llega como número (67 es «C»).
    if isinstance(raw, int) and not isinstance(raw, bool):
        return chr(raw).upper() if raw and chr(raw).isalpha() else None
    text = clean_text(raw)
    if text is None:
        return None
    letter = text[0]
    return letter.upper() if letter.isalpha() else None


@dataclass(frozen=True)
class _VolumeIndex:
    by_letter: dict[str, dict[str, Any]]
    by_path: dict[str, dict[str, Any]]


class StorageCollector:
    name = "storage"
    timeout_s = 60.0

    def collect(self, ctx: CollectionContext) -> StorageSection:
        physical_r, disk_r, partition_r, volume_r = ctx.query(
            [_MSFT_PHYSICAL, _MSFT_DISK, _MSFT_PARTITION, _MSFT_VOLUME]
        )
        if physical_r.ok and physical_r.rows:
            controllers = self._controllers(ctx)
            return self._from_storage_namespace(
                ctx, physical_r, disk_r, partition_r, volume_r, controllers
            )
        ctx.warn(
            "storage_namespace_unavailable",
            "Se usa Win32_DiskDrive: la clasificación de las unidades es menos precisa",
            _MSFT_PHYSICAL.source,
        )
        return self._from_win32(ctx)

    # --- Fuente preferida: root/Microsoft/Windows/Storage -------------------------------------

    def _from_storage_namespace(
        self,
        ctx: CollectionContext,
        physical_r: CimResult,
        disk_r: CimResult,
        partition_r: CimResult,
        volume_r: CimResult,
        controllers: dict[int, str] | None = None,
    ) -> StorageSection:
        source = _MSFT_PHYSICAL.source
        external: list[PhysicalDisk] = []
        disks_by_number = {
            row.get("Number"): dict(row) for row in disk_r.rows if row.get("Number") is not None
        }
        partitions_by_disk: dict[int, list[dict[str, Any]]] = {}
        for row in partition_r.rows:
            number = row.get("DiskNumber")
            if isinstance(number, int):
                partitions_by_disk.setdefault(number, []).append(dict(row))
        volumes = self._volume_index(volume_r)

        disks: list[PhysicalDisk] = []
        excluded: list[ExcludedDisk] = []
        for row in physical_r.rows:
            bus = BUS_BY_CODE.get(row.get("BusType"), DiskBus.UNKNOWN)  # type: ignore[arg-type]
            model = clean_text(row.get("FriendlyName")) or clean_text(row.get("Model"))
            reason = exclusion_reason(bus)
            if reason and reason not in EXTERNAL_REASONS:
                excluded.append(ExcludedDisk(model=model, bus=bus, reason=reason))
                continue
            number = self._disk_number(row.get("DeviceId"))
            media = row.get("MediaType")
            spindle = row.get("SpindleSpeed")
            classification = classify_disk(
                bus,
                media if isinstance(media, int) else None,
                spindle if isinstance(spindle, int) else None,
            )
            disk_info = disks_by_number.get(number, {})
            is_boot = disk_info.get("IsBoot")
            if not isinstance(is_boot, bool):
                is_boot = None
            if isinstance(disk_info.get("IsSystem"), bool):
                is_boot = bool(is_boot) or bool(disk_info.get("IsSystem"))
            health = row.get("HealthStatus")
            health_text = _HEALTH.get(health) if isinstance(health, int) else None
            vendor = clean_text(row.get("Manufacturer"))
            inferred = None if vendor else disk_vendor(model)
            (external if reason else disks).append(
                PhysicalDisk(
                    number=(
                        Observed[int].reported(number, f"{source}.DeviceId")
                        if number is not None
                        else Observed[int].unknown(Reason.NOT_REPORTED, f"{source}.DeviceId")
                    ),
                    manufacturer=(
                        Observed[str].inferred(inferred, "rule:model_prefix")
                        if inferred
                        else observed_text(vendor, f"{source}.Manufacturer")
                    ),
                    model=observed_text(model, f"{source}.FriendlyName"),
                    # Un disco externo no es parte del equipo: su serial no se guarda.
                    serial_number=(
                        Observed[str].unknown("external_not_collected", f"{source}.SerialNumber")
                        if reason
                        else observed_text(row.get("SerialNumber"), f"{source}.SerialNumber")
                    ),
                    capacity_bytes=observed_positive_int(row.get("Size"), f"{source}.Size"),
                    kind=self._kind(classification.kind, classification.rule),
                    bus=bus,
                    is_boot_disk=(
                        Observed[bool].reported(is_boot, f"{_MSFT_DISK.source}.IsBoot")
                        if is_boot is not None
                        else (
                            unknown_from(disk_r, _MSFT_DISK.source)
                            if not disk_r.ok
                            else Observed[bool].unknown(Reason.NOT_REPORTED, _MSFT_DISK.source)
                        )
                    ),
                    health=(
                        Observed[str].reported(health_text, f"{source}.HealthStatus")
                        if health_text
                        else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.HealthStatus")
                    ),
                    partitions=[
                        self._partition(row_p, volumes)
                        for row_p in sorted(
                            partitions_by_disk.get(-1 if number is None else number, []),
                            key=lambda p: p.get("PartitionNumber") or 0,
                        )
                    ],
                    controller_vendor=(controllers or {}).get(-1 if number is None else number),
                )
            )
        return StorageSection(
            disks=disks, excluded=excluded, detection_source=source, external=external
        )

    @staticmethod
    def _controllers(ctx: CollectionContext) -> dict[int, str]:
        """Número de disco → marca de su controladora (Phison, Samsung…), por el árbol de
        dispositivos. Opcional: sin árbol o sin Win32_DiskDrive no se informa."""
        tree = ctx.ports.devices
        if tree is None:
            return {}
        try:
            drives = ctx.query([_WIN32_DISK], optional=[_WIN32_DISK])[0]
            nodes = {n.instance_id.upper(): n for n in tree.nodes(_CONTROLLER_CLASSES)}
        except Exception:  # noqa: BLE001 - la marca de la controladora es un dato adicional
            return {}
        found: dict[int, str] = {}
        for row in drives.rows:
            index = row.get("Index")
            node = nodes.get(str(row.get("PNPDeviceID") or "").upper())
            if not isinstance(index, int) or node is None:
                continue
            vendor = controller_vendor(node.parent)
            if vendor:
                found[index] = vendor
        return found

    @staticmethod
    def _kind(kind: DiskKind | None, rule: str) -> Observed[DiskKind]:
        if kind is None:
            return Observed[DiskKind].unknown(rule, _MSFT_PHYSICAL.source)
        return Observed[DiskKind].inferred(kind, f"rule:{rule}")

    @staticmethod
    def _disk_number(raw: Any) -> int | None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _volume_index(result: CimResult) -> _VolumeIndex:
        by_letter: dict[str, dict[str, Any]] = {}
        by_path: dict[str, dict[str, Any]] = {}
        for row in result.rows:
            letter = _letter(row.get("DriveLetter"))
            if letter:
                by_letter[letter] = dict(row)
            path = clean_text(row.get("Path"))
            if path:
                by_path[path.lower()] = dict(row)
        return _VolumeIndex(by_letter, by_path)

    def _partition(self, row: dict[str, Any], volumes: _VolumeIndex) -> Partition:
        source = _MSFT_PARTITION.source
        letter = _letter(row.get("DriveLetter"))
        volume_row = volumes.by_letter.get(letter) if letter else None
        if volume_row is None:
            paths = row.get("AccessPaths")
            for path in paths if isinstance(paths, list) else []:
                volume_row = volumes.by_path.get(str(path).lower())
                if volume_row:
                    break
        gpt = clean_text(row.get("GptType"))
        number = row.get("PartitionNumber")
        return Partition(
            number=number if isinstance(number, int) else 0,
            drive_letter=letter,
            size_bytes=observed_positive_int(row.get("Size"), f"{source}.Size"),
            kind=_GPT_KINDS.get(gpt.lower(), "other_gpt") if gpt else None,
            volume=self._volume(volume_row, letter) if volume_row else None,
        )

    @staticmethod
    def _volume(row: dict[str, Any], letter: str | None) -> Volume:
        source = _MSFT_VOLUME.source
        size = observed_positive_int(row.get("Size"), f"{source}.Size")
        free_raw = row.get("SizeRemaining")
        free = (
            Observed[int].reported(free_raw, f"{source}.SizeRemaining")
            if isinstance(free_raw, int) and not isinstance(free_raw, bool) and free_raw >= 0
            else Observed[int].unknown(Reason.NOT_REPORTED, f"{source}.SizeRemaining")
        )
        used = (
            Observed[int].inferred(size.value - free.value, "rule:size_minus_free")
            if size.value is not None and free.value is not None and size.value >= free.value
            else Observed[int].unknown(Reason.NOT_REPORTED, "rule:size_minus_free")
        )
        return Volume(
            drive_letter=letter,
            label=clean_text(row.get("FileSystemLabel")),
            file_system=clean_text(row.get("FileSystem")),
            size_bytes=size,
            free_bytes=free,
            used_bytes=used,
        )

    # --- Alternativa: Win32_DiskDrive ----------------------------------------------------------

    def _from_win32(self, ctx: CollectionContext) -> StorageSection:
        result = ctx.query([_WIN32_DISK])[0]
        source = _WIN32_DISK.source
        if not result.ok:
            raise ModuleFailed("query_failed", "No se pudieron consultar las unidades", source)
        disks: list[PhysicalDisk] = []
        excluded: list[ExcludedDisk] = []
        for row in result.rows:
            pnp = clean_text(row.get("PNPDeviceID"))
            interface = (clean_text(row.get("InterfaceType")) or "").upper()
            bus = _WIN32_BUS.get(interface, DiskBus.UNKNOWN)
            upper_pnp = (pnp or "").upper()
            if "VEN_NVME" in upper_pnp or upper_pnp.startswith("NVME"):
                bus = DiskBus.NVME
            model = clean_text(row.get("Model"))
            media_hint = (clean_text(row.get("MediaType")) or "").lower()
            if pnp_says_usb(pnp):
                excluded.append(ExcludedDisk(model=model, bus=DiskBus.USB, reason="external_usb"))
                continue
            reason = exclusion_reason(bus)
            if reason:
                excluded.append(ExcludedDisk(model=model, bus=bus, reason=reason))
                continue
            if media_hint.startswith("external") or media_hint.startswith("removable"):
                excluded.append(ExcludedDisk(model=model, bus=bus, reason="removable_media"))
                continue
            classification = classify_disk(bus, None, None)
            index = row.get("Index")
            disks.append(
                PhysicalDisk(
                    number=(
                        Observed[int].reported(index, f"{source}.Index")
                        if isinstance(index, int)
                        else Observed[int].unknown(Reason.NOT_REPORTED, f"{source}.Index")
                    ),
                    manufacturer=observed_text(row.get("Manufacturer"), f"{source}.Manufacturer"),
                    model=observed_text(model, f"{source}.Model"),
                    serial_number=observed_text(row.get("SerialNumber"), f"{source}.SerialNumber"),
                    capacity_bytes=observed_positive_int(row.get("Size"), f"{source}.Size"),
                    kind=(
                        Observed[DiskKind].inferred(
                            classification.kind, f"rule:{classification.rule}"
                        )
                        if classification.kind
                        else Observed[DiskKind].unknown("win32_diskdrive_has_no_media_type", source)
                    ),
                    bus=bus,
                    is_boot_disk=Observed[bool].unknown(Reason.NOT_AVAILABLE, source),
                    health=Observed[str].unknown(Reason.NOT_AVAILABLE, source),
                    partitions=[],
                )
            )
        return StorageSection(disks=disks, excluded=excluded, detection_source=source)
