"""Módulos de hardware con respuestas WMI simuladas (mocks) por fabricante."""

from __future__ import annotations

from typing import Any

import pytest

from fakes import FakeCim, FakeNative, make_context, make_ports
from fixtures.vendors import ACER, ALL_VENDORS, DELL, GIB, HP, LENOVO, PCSMART
from honey_check.application.collection import ModuleFailed
from honey_check.application.ports import CimErrorKind
from honey_check.domain.classification import DeviceType, DiskBus, DiskKind
from honey_check.domain.observed import Confidence, Reason
from honey_check.infrastructure.collectors.hardware import (
    IdentityCollector,
    MemoryCollector,
    ProcessorCollector,
    StorageCollector,
)


def context_for(rows: dict[str, list[dict[str, Any]]], **kwargs: Any) -> Any:
    return make_context(make_ports(cim=FakeCim(rows, kwargs.pop("errors", None)), **kwargs))


class TestVendorMatrix:
    @pytest.mark.parametrize("vendor", ALL_VENDORS)
    def test_all_hardware_modules_produce_valid_sections(self, vendor: str) -> None:
        rows = ALL_VENDORS[vendor]
        for collector in (
            IdentityCollector(),
            ProcessorCollector(),
            MemoryCollector(),
            StorageCollector(),
        ):
            section = collector.collect(context_for(rows))
            assert section.model_dump(mode="json", by_alias=True)

    @pytest.mark.parametrize(
        ("rows", "maker", "kind"),
        [
            (ACER, "Acer", DeviceType.DESKTOP),
            (HP, "HP", DeviceType.LAPTOP),
            (LENOVO, "LENOVO", DeviceType.LAPTOP),
            (DELL, "Dell Inc.", DeviceType.MINI_PC),
        ],
    )
    def test_identity_of_branded_machines(self, rows: dict, maker: str, kind: DeviceType) -> None:
        identity = IdentityCollector().collect(context_for(rows))
        assert identity.manufacturer.value == maker
        assert identity.serial_number.value
        assert identity.device_type.value is kind
        assert identity.device_type.confidence is Confidence.INFERRED
        assert identity.membership.kind.value == "domain"
        assert identity.firmware.mode.value == "uefi"

    def test_assembled_pc_placeholders_are_never_shown_as_data(self) -> None:
        identity = IdentityCollector().collect(context_for(PCSMART))
        assert identity.manufacturer.value is None
        assert identity.manufacturer.reason == Reason.PLACEHOLDER
        assert identity.manufacturer.raw == "To Be Filled By O.E.M."
        assert identity.model.value is None
        assert identity.serial_number.value is None
        assert identity.serial_number.reason == Reason.PLACEHOLDER
        assert identity.system_uuid.value is None
        assert identity.sku.value is None
        assert identity.baseboard.product.value == "H610M Ficticia"
        assert identity.membership.kind.value == "workgroup"

    def test_serial_falls_back_to_product_when_bios_is_filler(self) -> None:
        rows = {
            **PCSMART,
            "Win32_ComputerSystemProduct": [{"IdentifyingNumber": "PROD-SERIE", "UUID": None}],
        }
        identity = IdentityCollector().collect(context_for(rows))
        assert identity.serial_number.value == "PROD-SERIE"


class TestIdentityFailures:
    def test_partial_failure_keeps_other_classes(self) -> None:
        ctx = context_for(ACER, errors={"Win32_BIOS": CimErrorKind.FAILED})
        identity = IdentityCollector().collect(ctx)
        assert identity.manufacturer.value == "Acer"
        assert identity.firmware.version.value is None
        assert identity.firmware.version.reason == Reason.QUERY_FAILED
        assert [e.source for e in ctx.errors] == ["cim:root/cimv2/Win32_BIOS"]

    def test_all_failed_is_module_failure(self) -> None:
        errors = dict.fromkeys(
            [
                "Win32_ComputerSystem",
                "Win32_ComputerSystemProduct",
                "Win32_BIOS",
                "Win32_BaseBoard",
                "Win32_SystemEnclosure",
            ],
            CimErrorKind.TRANSIENT,
        )
        with pytest.raises(ModuleFailed):
            IdentityCollector().collect(context_for({}, errors=errors))

    def test_access_denied_is_a_warning_with_reason(self) -> None:
        ctx = context_for(ACER, errors={"Win32_BaseBoard": CimErrorKind.ACCESS_DENIED})
        identity = IdentityCollector().collect(ctx)
        assert identity.baseboard.product.reason == Reason.ACCESS_DENIED
        assert ctx.errors == []
        assert ctx.warnings[0].code == "access_denied"

    def test_native_hostname_is_preferred(self) -> None:
        identity = IdentityCollector().collect(
            context_for(ACER, native=FakeNative(hostname="NOMBRE-LARGO-FICTICIO-16"))
        )
        assert identity.hostname.value == "NOMBRE-LARGO-FICTICIO-16"

    def test_hostname_falls_back_to_wmi(self) -> None:
        identity = IdentityCollector().collect(context_for(ACER, native=FakeNative(hostname=None)))
        assert identity.hostname.value == "PC-ACER-FICTICIO"


class TestProcessor:
    def test_values(self) -> None:
        section = ProcessorCollector().collect(context_for(LENOVO))
        processor = section.processors[0]
        assert processor.manufacturer.value == "AuthenticAMD"
        assert processor.physical_cores.value == 8
        assert processor.logical_processors.value == 16
        assert processor.architecture.value == "x64"
        assert section.total_logical_processors.value == 16

    def test_multi_socket_totals(self) -> None:
        cpu = HP["Win32_Processor"][0]
        section = ProcessorCollector().collect(context_for({"Win32_Processor": [cpu, cpu]}))
        assert section.total_physical_cores.value == 8

    def test_zero_cores_is_unknown(self) -> None:
        cpu = {**HP["Win32_Processor"][0], "NumberOfCores": 0}
        section = ProcessorCollector().collect(context_for({"Win32_Processor": [cpu]}))
        assert section.processors[0].physical_cores.value is None
        assert section.total_physical_cores.value is None

    def test_wmi_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            ProcessorCollector().collect(
                context_for({}, errors={"Win32_Processor": CimErrorKind.FAILED})
            )

    def test_no_rows(self) -> None:
        with pytest.raises(ModuleFailed):
            ProcessorCollector().collect(context_for({}))


class TestMemory:
    def test_ddr4_single_module_and_free_slot(self) -> None:
        section = MemoryCollector().collect(context_for(ACER))
        assert section.module_count == 1
        assert section.modules[0].memory_type.value == "DDR4"
        assert section.modules[0].memory_type.source.endswith("SMBIOSMemoryType")
        assert section.installed_bytes.value == 8 * GIB
        assert section.total_slots.value == 2
        assert section.free_slots.value == 1

    def test_ddr4_two_modules_no_free_slot(self) -> None:
        section = MemoryCollector().collect(context_for(HP))
        assert section.module_count == 2
        assert section.installed_bytes.value == 16 * GIB
        assert section.free_slots.value == 0
        assert section.modules[0].part_number.value == "DDR4-FICT-A"

    def test_ddr5_two_modules(self) -> None:
        section = MemoryCollector().collect(context_for(LENOVO))
        assert {m.memory_type.value for m in section.modules} == {"DDR5"}
        assert section.installed_bytes.value == 32 * GIB
        assert section.modules[0].speed_mts.value == 5600
        assert section.modules[0].form_factor.value == "SODIMM"

    def test_unknown_type_is_not_deduced_from_frequency(self) -> None:
        """Un módulo de 3200 MT/s sin código SMBIOS sigue siendo de tipo desconocido."""
        module = {**ACER["Win32_PhysicalMemory"][0], "SMBIOSMemoryType": 0, "MemoryType": 0}
        section = MemoryCollector().collect(context_for({"Win32_PhysicalMemory": [module]}))
        assert section.modules[0].memory_type.value is None
        assert section.modules[0].memory_type.confidence is Confidence.UNKNOWN
        assert section.modules[0].speed_mts.value == 3200

    def test_legacy_memory_type_is_used_when_smbios_is_empty(self) -> None:
        module = {**ACER["Win32_PhysicalMemory"][0], "SMBIOSMemoryType": 0, "MemoryType": 24}
        section = MemoryCollector().collect(context_for({"Win32_PhysicalMemory": [module]}))
        assert section.modules[0].memory_type.value == "DDR3"
        assert section.modules[0].memory_type.source.endswith(".MemoryType")

    def test_filler_values_are_not_data(self) -> None:
        section = MemoryCollector().collect(context_for(PCSMART))
        module = section.modules[0]
        assert module.memory_type.value is None
        assert module.manufacturer.value is None
        assert module.part_number.value is None
        assert module.serial_number.value is None
        assert section.total_slots.value is None
        assert section.free_slots.value is None

    def test_contradictory_smbios_does_not_report_negative_slots(self) -> None:
        rows = {**HP, "Win32_PhysicalMemoryArray": [{"MemoryDevices": 1, "Use": 3}]}
        ctx = context_for(rows)
        section = MemoryCollector().collect(ctx)
        assert section.free_slots.value is None
        assert section.free_slots.reason == Reason.INVALID_VALUE
        assert ctx.warnings[0].code == "inconsistent_memory_slots"

    def test_module_query_failure_keeps_total(self) -> None:
        ctx = context_for(ACER, errors={"Win32_PhysicalMemory": CimErrorKind.FAILED})
        section = MemoryCollector().collect(ctx)
        assert section.modules == []
        assert section.installed_bytes.reason == Reason.QUERY_FAILED
        assert section.visible_to_os_bytes.value == 15 * GIB
        assert ctx.errors

    def test_total_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            MemoryCollector().collect(
                context_for(
                    {},
                    errors={
                        "Win32_PhysicalMemory": CimErrorKind.FAILED,
                        "Win32_ComputerSystem": CimErrorKind.FAILED,
                    },
                )
            )


class TestStorage:
    def test_nvme(self) -> None:
        section = StorageCollector().collect(context_for(ACER))
        disk = section.disks[0]
        assert disk.kind.value is DiskKind.SSD_NVME
        assert disk.bus is DiskBus.NVME
        assert disk.serial_number.value == "NVME-SERIE-A"
        assert disk.is_boot_disk.value is True

    def test_sata_ssd_and_hdd(self) -> None:
        section = StorageCollector().collect(context_for(HP))
        assert [d.kind.value for d in section.disks] == [DiskKind.SSD_SATA, DiskKind.HDD]
        assert section.disks[1].is_boot_disk.value is False

    def test_usb_ssd_is_listed_as_external_without_its_serial(self) -> None:
        usb = {
            "DeviceId": "2",
            "FriendlyName": "SSD Externo Ficticio",
            "SerialNumber": "USB-SERIE-SECRETA",
            "Size": 1000 * GIB,
            "BusType": 7,
            "MediaType": 4,
            "SpindleSpeed": 0,
            "HealthStatus": 0,
        }
        rows = {**ACER, "MSFT_PhysicalDisk": [*ACER["MSFT_PhysicalDisk"], usb]}
        section = StorageCollector().collect(context_for(rows))
        assert len(section.disks) == 1
        assert section.external[0].model.value == "SSD Externo Ficticio"
        assert section.excluded == []
        assert "USB-SERIE-SECRETA" not in section.model_dump_json()

    def test_drive_letter_arrives_as_a_number_from_com(self) -> None:
        from honey_check.infrastructure.collectors.hardware import _letter

        assert (_letter(67), _letter("D"), _letter(0), _letter(None)) == ("C", "D", None, None)

    def test_vendor_is_inferred_from_the_model_when_windows_leaves_it_empty(self) -> None:
        from honey_check.domain.classification import controller_vendor, disk_vendor

        assert disk_vendor("WDC WD10EZEX-00BN5A0") == "Western Digital"
        assert disk_vendor("ST1000DM010") == "Seagate"
        assert disk_vendor("Modelo Ficticio 512") is None
        assert controller_vendor(r"PCI\VEN_1987&DEV_0001&SUBSYS_00000000") == "Phison"

    def test_uncertain_disk_is_declared(self) -> None:
        section = StorageCollector().collect(context_for(PCSMART))
        disk = section.disks[0]
        assert disk.kind.value is None
        assert disk.kind.confidence is Confidence.UNKNOWN
        assert disk.kind.reason == "media_type_unspecified"
        assert disk.serial_number.value is None

    def test_partitions_and_volumes_of_disk_zero(self) -> None:
        """Regresión: el disco 0 perdía sus particiones por tratar 0 como ausente."""
        rows = {
            **ACER,
            "MSFT_Partition": [
                {
                    "DiskNumber": 0,
                    "PartitionNumber": 1,
                    "DriveLetter": None,
                    "Size": 260 * 1024**2,
                    "GptType": "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}",
                    "AccessPaths": ["\\\\?\\Volume{a}\\"],
                },
                {
                    "DiskNumber": 0,
                    "PartitionNumber": 3,
                    "DriveLetter": "C",
                    "Size": 400 * GIB,
                    "GptType": "{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}",
                    "AccessPaths": ["C:\\", "\\\\?\\Volume{c}\\"],
                },
            ],
            "MSFT_Volume": [
                {
                    "Path": "\\\\?\\Volume{c}\\",
                    "DriveLetter": "C",
                    "FileSystemLabel": "Sistema",
                    "FileSystem": "NTFS",
                    "Size": 400 * GIB,
                    "SizeRemaining": 100 * GIB,
                },
                {
                    "Path": "\\\\?\\Volume{a}\\",
                    "DriveLetter": None,
                    "FileSystemLabel": "",
                    "FileSystem": "FAT32",
                    "Size": 260 * 1024**2,
                    "SizeRemaining": 200 * 1024**2,
                },
            ],
        }
        disk = StorageCollector().collect(context_for(rows)).disks[0]
        assert [p.number for p in disk.partitions] == [1, 3]
        assert disk.partitions[0].kind == "efi_system"
        assert disk.partitions[0].volume is not None
        assert disk.partitions[0].volume.file_system == "FAT32"
        volume = disk.partitions[1].volume
        assert volume is not None
        assert volume.drive_letter == "C"
        assert volume.free_bytes.value == 100 * GIB
        assert volume.used_bytes.value == 300 * GIB
        assert volume.used_bytes.confidence is Confidence.INFERRED

    def test_falls_back_to_win32_diskdrive(self) -> None:
        rows = {
            "Win32_DiskDrive": [
                {
                    "Index": 0,
                    "Model": "NVMe Ficticio",
                    "SerialNumber": "S1",
                    "Size": 512 * GIB,
                    "InterfaceType": "SCSI",
                    "PNPDeviceID": "SCSI\\DISK&VEN_NVME&PROD_FICTICIO\\5&1",
                    "MediaType": "Fixed hard disk media",
                },
                {
                    "Index": 1,
                    "Model": "Disco ATA Ficticio",
                    "SerialNumber": "S2",
                    "Size": 256 * GIB,
                    "InterfaceType": "IDE",
                    "PNPDeviceID": "SCSI\\DISK&VEN_ATA\\5&2",
                    "MediaType": "Fixed hard disk media",
                },
                {
                    "Index": 2,
                    "Model": "USB Ficticio",
                    "SerialNumber": "S3",
                    "Size": 64 * GIB,
                    "InterfaceType": "USB",
                    "PNPDeviceID": "USBSTOR\\DISK&VEN_FICTICIO\\1",
                    "MediaType": "Removable Media",
                },
            ]
        }
        ctx = context_for(rows, errors={"MSFT_PhysicalDisk": CimErrorKind.NOT_AVAILABLE})
        section = StorageCollector().collect(ctx)
        assert section.detection_source.endswith("Win32_DiskDrive")
        assert [d.number.value for d in section.disks] == [0, 1]
        assert section.disks[0].kind.value is DiskKind.SSD_NVME
        # Win32_DiskDrive no distingue HDD de SSD: se declara, no se adivina.
        assert section.disks[1].kind.value is None
        assert section.excluded[0].bus is DiskBus.USB
        assert any(w.code == "storage_namespace_unavailable" for w in ctx.warnings)

    def test_total_failure(self) -> None:
        with pytest.raises(ModuleFailed):
            StorageCollector().collect(
                context_for(
                    {},
                    errors={
                        "MSFT_PhysicalDisk": CimErrorKind.ACCESS_DENIED,
                        "Win32_DiskDrive": CimErrorKind.ACCESS_DENIED,
                    },
                )
            )
