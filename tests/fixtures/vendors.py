"""Respuestas WMI ficticias por fabricante.

Los nombres de marca son reales porque el producto debe reconocerlos; los modelos, seriales y
nombres de equipo son inventados y no provienen de ningún equipo real. Reproducen las rarezas
conocidas de cada tipo de equipo (relleno de SMBIOS en ensamblados, módulos soldados, etc.).
"""

from __future__ import annotations

from typing import Any

GIB = 1024**3


def _disk(
    number: int, name: str, serial: str, size: int, bus: int, media: int, spindle: int = 0
) -> dict[str, Any]:
    return {
        "DeviceId": str(number),
        "FriendlyName": name,
        "Manufacturer": None,
        "Model": name,
        "SerialNumber": serial,
        "Size": size,
        "BusType": bus,
        "MediaType": media,
        "SpindleSpeed": spindle,
        "HealthStatus": 0,
    }


def _ram(
    capacity: int,
    smbios: int,
    speed: int,
    locator: str,
    part: str,
    manufacturer: str = "Fabricante Ficticio",
    form: int = 12,
) -> dict[str, Any]:
    return {
        "Capacity": capacity,
        "SMBIOSMemoryType": smbios,
        "MemoryType": 0,
        "Speed": speed,
        "ConfiguredClockSpeed": speed,
        "Manufacturer": manufacturer,
        "PartNumber": part + "   ",
        "SerialNumber": "RAM-SERIE-FICTICIA",
        "DeviceLocator": locator,
        "BankLabel": "BANK 0",
        "FormFactor": form,
    }


def _cpu(name: str, maker: str, cores: int, threads: int, mhz: int) -> dict[str, Any]:
    return {
        "Name": name,
        "Manufacturer": maker,
        "Architecture": 9,
        "NumberOfCores": cores,
        "NumberOfLogicalProcessors": threads,
        "MaxClockSpeed": mhz,
        "SocketDesignation": "U3E1",
        "AddressWidth": 64,
        "L2CacheSize": 5120,
        "L3CacheSize": 12288,
        "VirtualizationFirmwareEnabled": True,
    }


def _system(manufacturer: str, model: str, name: str, pc_type: int) -> dict[str, Any]:
    return {
        "Name": name,
        "Manufacturer": manufacturer,
        "Model": model,
        "SystemSKUNumber": "SKU-FICTICIO",
        "SystemType": "x64-based PC",
        "PCSystemType": pc_type,
        "PCSystemTypeEx": pc_type,
        "Domain": "DOMINIO.EJEMPLO",
        "PartOfDomain": True,
        "Workgroup": None,
        "TotalPhysicalMemory": 15 * GIB,
    }


def _bios(vendor: str, version: str, serial: str) -> dict[str, Any]:
    return {
        "Manufacturer": vendor,
        "SMBIOSBIOSVersion": version,
        "SMBIOSMajorVersion": 3,
        "SMBIOSMinorVersion": 4,
        "ReleaseDate": "2025-03-14T00:00:00.0000000Z",
        "SerialNumber": serial,
    }


ACER: dict[str, list[dict[str, Any]]] = {
    "Win32_ComputerSystem": [_system("Acer", "Veriton Ficticio N1", "PC-ACER-FICTICIO", 1)],
    "Win32_ComputerSystemProduct": [
        {"IdentifyingNumber": "ACER-SERIE-0001", "UUID": "11111111-1111-4111-8111-111111111111"}
    ],
    "Win32_BIOS": [_bios("Insyde Corp.", "R01-A1", "ACER-SERIE-0001")],
    "Win32_BaseBoard": [
        {
            "Manufacturer": "Acer",
            "Product": "Placa Ficticia A",
            "SerialNumber": "PLACA-A-01",
            "Version": "1.0",
        }
    ],
    "Win32_SystemEnclosure": [{"ChassisTypes": [3], "SMBIOSAssetTag": "No Asset Tag"}],
    "Win32_Processor": [_cpu("Intel(R) Core(TM) i5 Ficticio", "GenuineIntel", 6, 12, 2500)],
    "Win32_PhysicalMemory": [_ram(8 * GIB, 26, 3200, "DIMM1", "DDR4-FICT-8G", form=8)],
    "Win32_PhysicalMemoryArray": [{"MemoryDevices": 2, "Use": 3}],
    "MSFT_PhysicalDisk": [_disk(0, "SSD NVMe Ficticio 512", "NVME-SERIE-A", 512 * GIB, 17, 4)],
    "MSFT_Disk": [{"Number": 0, "IsBoot": True, "IsSystem": True, "BusType": 17}],
}

HP: dict[str, list[dict[str, Any]]] = {
    "Win32_ComputerSystem": [_system("HP", "ProBook Ficticio 400", "PC-HP-FICTICIO", 2)],
    "Win32_ComputerSystemProduct": [
        {"IdentifyingNumber": "HP-SERIE-0002", "UUID": "22222222-2222-4222-8222-222222222222"}
    ],
    "Win32_BIOS": [_bios("HP", "T70 Ver. 01.10.00", "HP-SERIE-0002")],
    "Win32_BaseBoard": [
        {
            "Manufacturer": "HP",
            "Product": "8A5F",
            "SerialNumber": "PLACA-H-02",
            "Version": "KBC 1.0",
        }
    ],
    "Win32_SystemEnclosure": [{"ChassisTypes": [10], "SMBIOSAssetTag": "ACTIVO-HP-77"}],
    "Win32_Processor": [_cpu("11th Gen Intel(R) Core(TM) i7 Ficticio", "GenuineIntel", 4, 8, 2800)],
    "Win32_PhysicalMemory": [
        _ram(8 * GIB, 26, 3200, "Bottom-Slot 1(left)", "DDR4-FICT-A"),
        _ram(8 * GIB, 26, 3200, "Bottom-Slot 2(right)", "DDR4-FICT-B"),
    ],
    "Win32_PhysicalMemoryArray": [{"MemoryDevices": 2, "Use": 3}],
    "MSFT_PhysicalDisk": [
        _disk(0, "SSD SATA Ficticio 256", "SATA-SERIE-H", 256 * GIB, 11, 4),
        _disk(1, "HDD Ficticio 1T", "HDD-SERIE-H", 1000 * GIB, 11, 3, 5400),
    ],
    "MSFT_Disk": [
        {"Number": 0, "IsBoot": True, "IsSystem": True, "BusType": 11},
        {"Number": 1, "IsBoot": False, "IsSystem": False, "BusType": 11},
    ],
}

LENOVO: dict[str, list[dict[str, Any]]] = {
    # Lenovo publica el tipo de máquina en Model y el nombre comercial en Version.
    "Win32_ComputerSystem": [_system("LENOVO", "20XXFICT00", "PC-LENOVO-FICTICIO", 2)],
    "Win32_ComputerSystemProduct": [
        {"IdentifyingNumber": "LNV-SERIE-03", "UUID": "33333333-3333-4333-8333-333333333333"}
    ],
    "Win32_BIOS": [_bios("LENOVO", "N32ET00W (1.10 )", "LNV-SERIE-03")],
    "Win32_BaseBoard": [
        {
            "Manufacturer": "LENOVO",
            "Product": "20XXFICT00",
            "SerialNumber": "PLACA-L-03",
            "Version": "SDK0",
        }
    ],
    "Win32_SystemEnclosure": [{"ChassisTypes": [10], "SMBIOSAssetTag": "No Asset Information"}],
    "Win32_Processor": [_cpu("AMD Ryzen 7 PRO Ficticio", "AuthenticAMD", 8, 16, 1900)],
    # DDR5 de dos módulos con fabricante reportado como código JEDEC.
    "Win32_PhysicalMemory": [
        _ram(16 * GIB, 34, 5600, "SODIMM1", "DDR5-FICT-16", manufacturer="80CE000080CE"),
        _ram(16 * GIB, 34, 5600, "SODIMM2", "DDR5-FICT-16", manufacturer="80CE000080CE"),
    ],
    "Win32_PhysicalMemoryArray": [{"MemoryDevices": 2, "Use": 3}],
    "MSFT_PhysicalDisk": [_disk(0, "NVMe Ficticio 1TB", "NVME-SERIE-L", 1000 * GIB, 17, 4)],
    "MSFT_Disk": [{"Number": 0, "IsBoot": True, "IsSystem": True, "BusType": 17}],
}

DELL: dict[str, list[dict[str, Any]]] = {
    "Win32_ComputerSystem": [_system("Dell Inc.", "OptiPlex Ficticio 3000", "PC-DELL-FICTICIO", 1)],
    "Win32_ComputerSystemProduct": [
        {"IdentifyingNumber": "DLLTAG5", "UUID": "44444444-4444-4444-8444-444444444444"}
    ],
    "Win32_BIOS": [_bios("Dell Inc.", "1.2.3", "DLLTAG5")],
    "Win32_BaseBoard": [
        {
            "Manufacturer": "Dell Inc.",
            "Product": "0FICT1",
            "SerialNumber": "/DLLTAG5/CNF/",
            "Version": "A00",
        }
    ],
    "Win32_SystemEnclosure": [{"ChassisTypes": [35], "SMBIOSAssetTag": ""}],
    "Win32_Processor": [_cpu("Intel(R) Core(TM) i3 Ficticio", "GenuineIntel", 4, 8, 3100)],
    "Win32_PhysicalMemory": [_ram(16 * GIB, 26, 2666, "DIMM1", "DDR4-FICT-16", form=8)],
    "Win32_PhysicalMemoryArray": [{"MemoryDevices": 4, "Use": 3}],
    "MSFT_PhysicalDisk": [_disk(0, "SSD Ficticio 256", "SSD-SERIE-D", 256 * GIB, 11, 4)],
    "MSFT_Disk": [{"Number": 0, "IsBoot": True, "IsSystem": True, "BusType": 11}],
}

# Equipo ensamblado: firmware genérico con valores de relleno en casi todo SMBIOS.
PCSMART: dict[str, list[dict[str, Any]]] = {
    "Win32_ComputerSystem": [
        {
            **_system("To Be Filled By O.E.M.", "To Be Filled By O.E.M.", "PC-SMART-FICTICIO", 1),
            "Domain": "WORKGROUP",
            "PartOfDomain": False,
            "Workgroup": "WORKGROUP",
            "SystemSKUNumber": "Default string",
        }
    ],
    "Win32_ComputerSystemProduct": [
        {"IdentifyingNumber": "Default string", "UUID": "00000000-0000-0000-0000-000000000000"}
    ],
    "Win32_BIOS": [_bios("American Megatrends Inc.", "P1.10", "Default string")],
    "Win32_BaseBoard": [
        {
            "Manufacturer": "Placa Generica",
            "Product": "H610M Ficticia",
            "SerialNumber": "Default string",
            "Version": "1.0",
        }
    ],
    "Win32_SystemEnclosure": [{"ChassisTypes": [3], "SMBIOSAssetTag": "Default string"}],
    "Win32_Processor": [_cpu("Intel(R) Core(TM) i3 Ficticio", "GenuineIntel", 4, 8, 3300)],
    # SMBIOS incompleto: sin tipo de memoria ni frecuencia. No debe deducirse nada.
    "Win32_PhysicalMemory": [
        {
            **_ram(8 * GIB, 0, 0, "ChannelA-DIMM0", "None", manufacturer="Unknown", form=0),
            "SerialNumber": "00000000",
        }
    ],
    # Contradictorio a propósito: una ranura reportada y dos módulos en la otra variante.
    "Win32_PhysicalMemoryArray": [{"MemoryDevices": 0, "Use": 3}],
    "MSFT_PhysicalDisk": [_disk(0, "SATA SSD 240GB", "0000000000000000", 240 * GIB, 11, 0)],
    "MSFT_Disk": [{"Number": 0, "IsBoot": True, "IsSystem": True, "BusType": 11}],
}

ALL_VENDORS = {"acer": ACER, "hp": HP, "lenovo": LENOVO, "dell": DELL, "pcsmart": PCSMART}
