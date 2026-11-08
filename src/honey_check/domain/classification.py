"""Reglas de clasificación independientes del sistema operativo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class DiskKind(StrEnum):
    HDD = "hdd"
    SSD_SATA = "ssd_sata"
    SSD_NVME = "ssd_nvme"
    SSD_SAS = "ssd_sas"
    SSD_OTHER = "ssd_other"
    EMMC = "emmc"


class DiskBus(StrEnum):
    NVME = "nvme"
    SATA = "sata"
    ATA = "ata"
    SAS = "sas"
    SCSI = "scsi"
    RAID = "raid"
    USB = "usb"
    SD = "sd"
    MMC = "mmc"
    FIREWIRE = "firewire"
    FIBRE_CHANNEL = "fibre_channel"
    ISCSI = "iscsi"
    VIRTUAL = "virtual"
    FILE_BACKED_VIRTUAL = "file_backed_virtual"
    STORAGE_SPACES = "storage_spaces"
    UNKNOWN = "unknown"


# Enumeración STORAGE_BUS_TYPE de Windows, tal como la expone MSFT_PhysicalDisk.BusType.
BUS_BY_CODE = {
    1: DiskBus.SCSI,
    2: DiskBus.ATA,  # ATAPI
    3: DiskBus.ATA,
    4: DiskBus.FIREWIRE,
    6: DiskBus.FIBRE_CHANNEL,
    7: DiskBus.USB,
    8: DiskBus.RAID,
    9: DiskBus.ISCSI,
    10: DiskBus.SAS,
    11: DiskBus.SATA,
    12: DiskBus.SD,
    13: DiskBus.MMC,
    14: DiskBus.VIRTUAL,
    15: DiskBus.FILE_BACKED_VIRTUAL,
    16: DiskBus.STORAGE_SPACES,
    17: DiskBus.NVME,
}

# Dispositivos que no son unidades físicas internas, aunque Windows los presente como fijos.
_EXCLUDED_BUSES = {
    DiskBus.USB: "external_usb",
    DiskBus.SD: "removable_card",
    DiskBus.FIREWIRE: "external_firewire",
    DiskBus.VIRTUAL: "virtual_disk",
    DiskBus.FILE_BACKED_VIRTUAL: "virtual_disk",
    DiskBus.STORAGE_SPACES: "storage_spaces_virtual_disk",
    DiskBus.ISCSI: "network_storage",
    DiskBus.FIBRE_CHANNEL: "network_storage",
}


def exclusion_reason(bus: DiskBus) -> str | None:
    return _EXCLUDED_BUSES.get(bus)


# Exclusiones de lo que sí está conectado por fuera: se muestra aparte, como disco externo.
EXTERNAL_REASONS = frozenset({"external_usb", "removable_card", "external_firewire"})

# Prefijos de modelo de las marcas de discos: Windows a menudo deja el fabricante vacío.
_MODEL_VENDORS = (
    ("SAMSUNG", "Samsung"),
    ("MZ", "Samsung"),
    ("WDC", "Western Digital"),
    ("WD", "Western Digital"),
    ("SANDISK", "SanDisk"),
    ("KINGSTON", "Kingston"),
    ("CRUCIAL", "Crucial"),
    ("CT", "Crucial"),
    ("MICRON", "Micron"),
    ("MTFD", "Micron"),
    ("SK HYNIX", "SK hynix"),
    ("HFM", "SK hynix"),
    ("HFS", "SK hynix"),
    ("INTEL", "Intel"),
    ("SSDPE", "Intel"),
    ("KIOXIA", "KIOXIA"),
    ("KBG", "KIOXIA"),
    ("KXG", "KIOXIA"),
    ("TOSHIBA", "Toshiba"),
    ("THNSN", "Toshiba"),
    ("SEAGATE", "Seagate"),
    ("ADATA", "ADATA"),
    ("XPG", "ADATA"),
    ("LEXAR", "Lexar"),
    ("LITEON", "Lite-On"),
    ("LITE-ON", "Lite-On"),
    ("HGST", "HGST"),
    ("HITACHI", "Hitachi"),
    ("TEAM", "Team Group"),
    ("PNY", "PNY"),
    ("PATRIOT", "Patriot"),
    ("NETAC", "Netac"),
    ("TRANSCEND", "Transcend"),
    ("HP SSD", "HP"),
    ("APPLE", "Apple"),
)


def disk_vendor(model: str | None) -> str | None:
    """Marca deducida del modelo («WDC WD10EZEX» → Western Digital), o None si no se reconoce."""
    upper = (model or "").strip().upper()
    if upper.startswith("ST") and upper[2:3].isdigit():
        return "Seagate"
    for prefix, vendor in _MODEL_VENDORS:
        if upper.startswith(prefix):
            return vendor
    return None


# Fabricantes de controladoras de almacenamiento por su identificador PCI (VEN_xxxx).
_CONTROLLER_VENDORS = {
    "1987": "Phison",
    "144D": "Samsung",
    "15B7": "Western Digital",
    "1C5C": "SK hynix",
    "126F": "Silicon Motion",
    "1344": "Micron",
    "1E0F": "KIOXIA",
    "1179": "Toshiba",
    "8086": "Intel",
    "1CC1": "ADATA",
    "2646": "Kingston",
    "1D97": "Lexar",
    "1E4B": "MAXIO",
    "1E49": "YMTC",
    "10EC": "Realtek",
    "1B4B": "Marvell",
    "1022": "AMD",
    "1B21": "ASMedia",
    "1BB1": "Seagate",
    "1CC4": "Union Memory",
    "1E95": "SSSTC",
    "1F40": "Netac",
    "1D79": "Transcend",
}


def controller_vendor(instance_id: str | None) -> str | None:
    """Fabricante de la controladora a partir de su identificador (`PCI\\VEN_1987&…`)."""
    match = re.search(r"VEN_([0-9A-F]{4})", (instance_id or "").upper())
    return _CONTROLLER_VENDORS.get(match.group(1)) if match else None


def pnp_says_usb(pnp_device_id: str | None) -> bool:
    upper = (pnp_device_id or "").upper()
    return upper.startswith(("USBSTOR\\", "USB\\", "UASPSTOR\\"))


@dataclass(frozen=True)
class DiskClassification:
    """`kind` nulo significa que la unidad no puede clasificarse con certeza."""

    kind: DiskKind | None
    # Regla aplicada, para poder auditar la clasificación desde el JSON.
    rule: str


def classify_disk(
    bus: DiskBus, media_type: int | None, spindle_rpm: int | None
) -> DiskClassification:
    """Clasifica por bus y propiedades físicas; ante la duda declara incertidumbre.

    `media_type` es MSFT_PhysicalDisk.MediaType: 3 HDD, 4 SSD, 5 SCM, 0 sin especificar.
    `spindle_rpm` solo cuenta como evidencia si es un valor positivo real: 0xFFFFFFFF y nulo
    significan «desconocido», y 0 por sí solo no demuestra que sea una unidad de estado sólido.
    """
    if bus is DiskBus.NVME:
        return DiskClassification(DiskKind.SSD_NVME, "bus_nvme")
    if bus is DiskBus.MMC:
        return DiskClassification(DiskKind.EMMC, "bus_mmc")

    rotates = spindle_rpm is not None and 0 < spindle_rpm < 0xFFFFFFFF
    if media_type == 3:
        return DiskClassification(DiskKind.HDD, "media_type_hdd")
    if media_type in (4, 5):
        if bus in (DiskBus.SATA, DiskBus.ATA):
            return DiskClassification(DiskKind.SSD_SATA, "media_type_ssd_bus_sata")
        if bus is DiskBus.SAS:
            return DiskClassification(DiskKind.SSD_SAS, "media_type_ssd_bus_sas")
        return DiskClassification(DiskKind.SSD_OTHER, f"media_type_ssd_bus_{bus.value}")
    if rotates:
        return DiskClassification(DiskKind.HDD, "spindle_speed_positive")
    return DiskClassification(None, "media_type_unspecified")


# SMBIOS tipo 17, campo «Memory Type» (DSP0134). Win32_PhysicalMemory.SMBIOSMemoryType.
_SMBIOS_MEMORY_TYPES = {
    15: "SDRAM",
    18: "DDR",
    20: "DDR",
    21: "DDR2",
    22: "DDR2 FB-DIMM",
    24: "DDR3",
    26: "DDR4",
    27: "LPDDR",
    28: "LPDDR2",
    29: "LPDDR3",
    30: "LPDDR4",
    31: "Logical non-volatile",
    32: "HBM",
    33: "HBM2",
    34: "DDR5",
    35: "LPDDR5",
    36: "HBM3",
}


def memory_type_from_smbios(code: int | None) -> str | None:
    """El tipo sale del código SMBIOS. Nunca se deduce de la frecuencia."""
    if code is None:
        return None
    return _SMBIOS_MEMORY_TYPES.get(code)


_FORM_FACTORS = {
    7: "SIMM",
    8: "DIMM",
    9: "TSOP",
    11: "RIMM",
    12: "SODIMM",
    13: "SRIMM",
    14: "FB-DIMM",
}


def memory_form_factor(code: int | None) -> str | None:
    return _FORM_FACTORS.get(code) if code is not None else None


class DeviceType(StrEnum):
    DESKTOP = "desktop"
    LAPTOP = "laptop"
    TABLET = "tablet"
    ALL_IN_ONE = "all_in_one"
    MINI_PC = "mini_pc"
    SERVER = "server"
    WORKSTATION = "workstation"
    VIRTUAL_MACHINE = "virtual_machine"
    OTHER = "other"


# SMBIOS tipo 3, «Chassis Type». Win32_SystemEnclosure.ChassisTypes.
_CHASSIS = {
    3: DeviceType.DESKTOP,
    4: DeviceType.DESKTOP,
    5: DeviceType.DESKTOP,
    6: DeviceType.DESKTOP,
    7: DeviceType.DESKTOP,
    8: DeviceType.LAPTOP,
    9: DeviceType.LAPTOP,
    10: DeviceType.LAPTOP,
    11: DeviceType.LAPTOP,
    12: DeviceType.LAPTOP,
    13: DeviceType.ALL_IN_ONE,
    14: DeviceType.LAPTOP,
    15: DeviceType.DESKTOP,
    16: DeviceType.DESKTOP,
    17: DeviceType.SERVER,
    23: DeviceType.SERVER,
    30: DeviceType.TABLET,
    31: DeviceType.LAPTOP,
    32: DeviceType.LAPTOP,
    35: DeviceType.MINI_PC,
    36: DeviceType.MINI_PC,
}
# Win32_ComputerSystem.PCSystemTypeEx.
_PC_SYSTEM_TYPE = {
    1: DeviceType.DESKTOP,
    2: DeviceType.LAPTOP,
    3: DeviceType.WORKSTATION,
    4: DeviceType.SERVER,
    5: DeviceType.SERVER,
    6: DeviceType.OTHER,
    7: DeviceType.WORKSTATION,
    8: DeviceType.TABLET,
}
_VIRTUAL_HINTS = ("virtual machine", "vmware", "virtualbox", "kvm", "qemu", "hvm domu", "bochs")


def device_type(
    chassis_types: list[int] | None, pc_system_type: int | None, model: str | None
) -> tuple[DeviceType | None, str | None]:
    """Devuelve el tipo y la regla usada. El chasis prevalece; 0, 1 y 2 significan «sin dato»."""
    lowered_model = (model or "").lower()
    if any(hint in lowered_model for hint in _VIRTUAL_HINTS):
        return DeviceType.VIRTUAL_MACHINE, "model_virtual_machine"
    for code in chassis_types or []:
        if code in _CHASSIS:
            return _CHASSIS[code], f"chassis_type_{code}"
    if pc_system_type in _PC_SYSTEM_TYPE:
        return _PC_SYSTEM_TYPE[pc_system_type], f"pc_system_type_{pc_system_type}"
    return None, None


_LTSC_EDITIONS = {"enterprises", "enterprisesn", "iotenterprises", "iotenterprisesk"}
WINDOWS_11_FIRST_BUILD = 22000


def windows_generation(build: int | None) -> str | None:
    """Windows 11 conserva `ProductName = Windows 10` en el Registro: se decide por compilación."""
    if build is None:
        return None
    if build >= WINDOWS_11_FIRST_BUILD:
        return "windows_11"
    if build >= 10240:
        return "windows_10"
    return "other"


def is_ltsc_edition(edition_id: str | None) -> bool | None:
    return edition_id.lower() in _LTSC_EDITIONS if edition_id else None


# Códigos ConfigManagerErrorCode documentados para Win32_PnPEntity.
DEVICE_ERRORS = {
    1: "El dispositivo no está configurado correctamente.",
    3: "El controlador podría estar dañado o faltan recursos del sistema.",
    9: "Windows no puede identificar este hardware.",
    10: "El dispositivo no puede iniciarse.",
    12: "No hay suficientes recursos libres para este dispositivo.",
    14: "El dispositivo requiere reiniciar el equipo.",
    18: "Es necesario reinstalar los controladores.",
    19: "La configuración en el Registro está incompleta o dañada.",
    21: "Windows está quitando este dispositivo.",
    22: "El dispositivo está deshabilitado.",
    24: "El dispositivo no está presente o no funciona correctamente.",
    28: "Los controladores no están instalados.",
    29: "El firmware no proporcionó los recursos necesarios.",
    31: "Windows no puede cargar los controladores requeridos.",
    32: "El servicio del controlador está deshabilitado.",
    37: "Windows no puede inicializar el controlador.",
    39: "El controlador está dañado o falta.",
    41: "El controlador se cargó, pero no encuentra el hardware.",
    43: "El dispositivo informó un problema y Windows lo detuvo.",
    45: "El dispositivo no está conectado actualmente.",
    47: "El dispositivo fue preparado para retirarlo con seguridad.",
    48: "El controlador está bloqueado por incompatibilidad.",
    51: "El dispositivo espera a otro dispositivo.",
    52: "Windows no puede verificar la firma digital del controlador.",
}


def decode_antivirus_state(product_state: int | None) -> tuple[bool | None, bool | None]:
    """Decodifica `productState` de SecurityCenter2 en (activo, firmas al día).

    Microsoft no documenta el formato: la decodificación es de uso común y por eso el
    resultado se publica como inferido.
    """
    if product_state is None:
        return None, None
    scanner = (product_state >> 8) & 0xFF
    signatures = product_state & 0xFF
    return scanner in (0x10, 0x11), signatures == 0x00
