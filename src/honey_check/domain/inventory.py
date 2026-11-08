"""Contrato del inventario: modelos tipados, versionados y sin dependencias de Windows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, PrivateAttr, model_validator

from .classification import DeviceType, DiskBus, DiskKind
from .observed import Confidence, Model, Observed, Reason

SCHEMA_NAME = "honey-check.inventory"
SCHEMA_VERSION = "2.2.0"


class ModuleStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class CollectionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class Issue(Model):
    module: str
    code: str
    message: str
    source: str | None = None


class ModuleReport(Model):
    name: str
    status: ModuleStatus
    duration_ms: int = Field(ge=0)
    retries: int = Field(default=0, ge=0)


# --- Identificación ---------------------------------------------------------------------------


class Baseboard(Model):
    manufacturer: Observed[str]
    product: Observed[str]
    serial_number: Observed[str]
    version: Observed[str]


class Firmware(Model):
    vendor: Observed[str]
    version: Observed[str]
    smbios_version: Observed[str]
    release_date: Observed[str]
    mode: Observed[str]


class DomainMembership(Model):
    kind: Observed[str]
    name: Observed[str]


class DeviceIdentity(Model):
    hostname: Observed[str]
    manufacturer: Observed[str]
    model: Observed[str]
    serial_number: Observed[str]
    system_uuid: Observed[str]
    sku: Observed[str]
    asset_tag: Observed[str]
    device_type: Observed[DeviceType]
    system_architecture: Observed[str]
    baseboard: Baseboard
    firmware: Firmware
    membership: DomainMembership


# --- Procesador -------------------------------------------------------------------------------


class Processor(Model):
    manufacturer: Observed[str]
    model: Observed[str]
    architecture: Observed[str]
    physical_cores: Observed[int]
    logical_processors: Observed[int]
    max_frequency_mhz: Observed[int]
    socket: Observed[str]
    address_width_bits: Observed[int]
    l2_cache_kib: Observed[int]
    l3_cache_kib: Observed[int]
    virtualization_firmware_enabled: Observed[bool]


class ProcessorSection(Model):
    processors: list[Processor]
    total_physical_cores: Observed[int]
    total_logical_processors: Observed[int]


# --- Memoria ----------------------------------------------------------------------------------


class MemoryModule(Model):
    capacity_bytes: Observed[int]
    memory_type: Observed[str]
    speed_mts: Observed[int]
    configured_speed_mts: Observed[int]
    manufacturer: Observed[str]
    part_number: Observed[str]
    serial_number: Observed[str]
    slot: Observed[str]
    bank: Observed[str]
    form_factor: Observed[str]


class MemorySection(Model):
    installed_bytes: Observed[int]
    visible_to_os_bytes: Observed[int]
    module_count: int = Field(ge=0)
    modules: list[MemoryModule]
    total_slots: Observed[int]
    free_slots: Observed[int]


# --- Almacenamiento ---------------------------------------------------------------------------


class Volume(Model):
    drive_letter: str | None
    label: str | None
    file_system: str | None
    size_bytes: Observed[int]
    free_bytes: Observed[int]
    used_bytes: Observed[int]


class Partition(Model):
    number: int
    drive_letter: str | None
    size_bytes: Observed[int]
    kind: str | None
    volume: Volume | None


class PhysicalDisk(Model):
    number: Observed[int]
    manufacturer: Observed[str]
    model: Observed[str]
    serial_number: Observed[str]
    capacity_bytes: Observed[int]
    kind: Observed[DiskKind]
    bus: DiskBus
    is_boot_disk: Observed[bool]
    health: Observed[str]
    partitions: list[Partition]
    # 2.2.0: marca de la controladora (NVMe, SATA) cuando Windows no da la del disco.
    controller_vendor: str | None = None


class ExcludedDisk(Model):
    """Se conserva como evidencia de la exclusión, sin serial."""

    model: str | None
    bus: DiskBus
    reason: str


class StorageSection(Model):
    disks: list[PhysicalDisk]
    excluded: list[ExcludedDisk]
    detection_source: str
    # 2.2.0: discos USB, tarjetas y FireWire conectados al analizar, con sus particiones y
    # letras. No son parte del equipo: su serial no se guarda.
    external: list[PhysicalDisk] = Field(default_factory=list)


# --- Sistema operativo ------------------------------------------------------------------------


class HotFix(Model):
    id: str
    description: str | None
    installed_on_raw: str | None


class OperatingSystem(Model):
    name: Observed[str]
    generation: Observed[str]
    edition_id: Observed[str]
    is_ltsc: Observed[bool]
    display_version: Observed[str]
    version: Observed[str]
    build: Observed[int]
    ubr: Observed[int]
    full_build: Observed[str]
    architecture: Observed[str]
    installed_at: Observed[datetime]
    last_boot_at: Observed[datetime]
    locale: Observed[str]
    hotfix_count: Observed[int]
    hotfixes: list[HotFix]


# --- Software ---------------------------------------------------------------------------------


class SoftwareScope(StrEnum):
    MACHINE = "machine"
    CURRENT_USER = "current_user"


class InstallerType(StrEnum):
    MSI = "msi"
    TRADITIONAL = "traditional"
    MSIX = "msix"
    OTHER = "other"
    UNKNOWN = "unknown"


class DetectionMechanism(StrEnum):
    REGISTRY_UNINSTALL = "registry_uninstall"
    APPX_PACKAGE = "appx_package"


class PathState(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    INACCESSIBLE = "inaccessible"
    NOT_PROVIDED = "not_provided"
    NOT_CHECKED = "not_checked"


class PathEvidence(Model):
    """Ruta con procedencia y con el resultado de comprobarla en el disco."""

    value: str | None = None
    confidence: Confidence = Confidence.UNKNOWN
    source: str | None = None
    state: PathState = PathState.NOT_PROVIDED
    reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.value is None:
            if self.confidence is not Confidence.UNKNOWN:
                raise ValueError("una ruta nula solo puede tener confianza 'unknown'")
            if not self.reason:
                raise ValueError("una ruta nula debe documentar el motivo")
            if self.state is not PathState.NOT_PROVIDED:
                raise ValueError("una ruta nula tiene estado 'not_provided'")
        elif not self.source:
            raise ValueError("una ruta presente debe declarar su origen")
        return self


class SignatureStatus(StrEnum):
    VALID = "valid"
    NOT_SIGNED = "not_signed"
    HASH_MISMATCH = "hash_mismatch"
    NOT_TRUSTED = "not_trusted"
    UNKNOWN_ERROR = "unknown_error"
    NOT_SUPPORTED = "not_supported"
    NOT_CHECKED = "not_checked"


class ExecutableSignature(Model):
    status: SignatureStatus
    signer: str | None = None
    reason: str | None = None


class ExecutableDetails(Model):
    file_version: str | None = None
    product_version: str | None = None
    product_name: str | None = None
    file_description: str | None = None
    company_name: str | None = None
    signature: ExecutableSignature = ExecutableSignature(
        status=SignatureStatus.NOT_CHECKED, reason=Reason.NOT_CHECKED
    )


class UninstallReference(Model):
    """Referencia informativa. Honey Check nunca la ejecuta."""

    command: str | None
    path: PathEvidence


class SoftwareItem(Model):
    id: str
    name: str
    version: Observed[str]
    publisher: Observed[str]
    scope: SoftwareScope
    installer_type: InstallerType
    mechanism: DetectionMechanism
    detection_source: str
    install_path: PathEvidence
    executable_path: PathEvidence
    uninstall: UninstallReference | None
    install_date: Observed[str]
    architecture: Observed[str]
    size_bytes: Observed[int]
    executable: ExecutableDetails | None
    package_full_name: str | None = None
    package_signature_kind: str | None = None
    is_system_component: bool = False
    is_framework: bool = False
    is_update: bool = False
    # Icono del programa guardado junto al inventario (equipos/<equipo>/iconos/<id>.png).
    icon_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")


class SoftwareSourceStatus(StrEnum):
    OK = "ok"
    NOT_PRESENT = "not_present"
    ACCESS_DENIED = "access_denied"
    FAILED = "failed"


class SoftwareSourceReport(Model):
    source: str
    status: SoftwareSourceStatus
    item_count: int = Field(ge=0)
    detail: str | None = None


class SoftwareSection(Model):
    items: list[SoftwareItem]
    total_count: int = Field(ge=0)
    executable_resolved_count: int = Field(ge=0)
    signature_checked_count: int = Field(ge=0)
    skipped_entries_without_name: int = Field(ge=0)
    sources: list[SoftwareSourceReport]
    limitations: list[str]


# --- Gráficos, pantallas, red, batería, TPM ----------------------------------------------------


class GraphicsAdapter(Model):
    name: Observed[str]
    vendor: Observed[str]
    driver_version: Observed[str]
    driver_date: Observed[datetime]
    memory_bytes: Observed[int]
    current_width_pixels: Observed[int]
    current_height_pixels: Observed[int]
    current_refresh_hz: Observed[int]
    status: Observed[str]


class GraphicsSection(Model):
    adapters: list[GraphicsAdapter]


class Monitor(Model):
    manufacturer_code: Observed[str]
    model: Observed[str]
    serial_number: Observed[str]
    year_of_manufacture: Observed[int]
    is_active: Observed[bool]


class DisplayMode(Model):
    device: str
    is_primary: bool
    width_pixels: int = Field(gt=0)
    height_pixels: int = Field(gt=0)
    refresh_hz: int | None


class DisplaySection(Model):
    monitors: list[Monitor]
    active_modes: list[DisplayMode]


class NetworkAdapter(Model):
    name: Observed[str]
    description: Observed[str]
    manufacturer: Observed[str]
    mac_address: Observed[str]
    connection: Observed[str]
    link_speed_bits_per_second: Observed[int]
    driver_version: Observed[str]
    ipv4_addresses: list[str]


class NetworkSection(Model):
    adapters: list[NetworkAdapter]
    detection_source: str


class Battery(Model):
    name: Observed[str]
    manufacturer: Observed[str]
    chemistry: Observed[str]
    charge_percent: Observed[int]
    status: Observed[str]
    design_capacity_mwh: Observed[int]
    full_charge_capacity_mwh: Observed[int]
    health_percent: Observed[int]
    cycle_count: Observed[int]


class BatterySection(Model):
    present: bool
    batteries: list[Battery]


class TpmSection(Model):
    present: Observed[bool]
    spec_version: Observed[str]
    manufacturer: Observed[str]
    firmware_version: Observed[str]
    enabled: Observed[bool]
    activated: Observed[bool]


# --- Dispositivos y seguridad ------------------------------------------------------------------


class ProblemDevice(Model):
    name: Observed[str]
    device_class: Observed[str]
    manufacturer: Observed[str]
    device_id: str | None
    error_code: int
    error_description: str | None
    status: Observed[str]


class DevicesSection(Model):
    total_count: Observed[int]
    problem_count: int = Field(ge=0)
    problems: list[ProblemDevice]


# --- Periféricos e impresoras -------------------------------------------------------------------


class PrinterConnection(StrEnum):
    NETWORK_TCP = "network_tcp"  # puerto TCP/IP estándar (IP o nombre)
    WSD = "wsd"  # descubierta por Web Services for Devices
    IPP = "ipp"  # Internet Printing Protocol / impresión universal
    USB = "usb"
    SHARED = "shared"  # cola compartida de otro equipo (\\servidor\impresora)
    VIRTUAL = "virtual"  # PDF, XPS, OneNote, fax, archivo
    LOCAL_OTHER = "local_other"  # LPT, COM u otro puerto local


class Printer(Model):
    name: str
    driver_name: Observed[str]
    manufacturer: Observed[str]
    driver_version: Observed[str]
    port_name: Observed[str]
    connection: PrinterConnection
    host_address: Observed[str]
    port_number: Observed[int]
    protocol: Observed[str]
    is_default: Observed[bool]
    is_shared: Observed[bool]
    share_name: Observed[str]
    status: Observed[str]
    detected_error: Observed[str]
    location: Observed[str]
    comment: Observed[str]
    serial_number: Observed[str]
    usb_vendor_id: str | None = None
    usb_product_id: str | None = None
    queued_jobs: Observed[int]


class PeripheralCategory(StrEnum):
    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    CAMERA = "camera"
    IMAGING = "imaging"  # escáneres y cámaras de imagen fija
    AUDIO = "audio"
    AUDIO_ENDPOINT = "audio_endpoint"
    BLUETOOTH = "bluetooth"
    SMART_CARD_READER = "smart_card_reader"
    SMART_CARD = "smart_card"
    BIOMETRIC = "biometric"
    PORTABLE_DEVICE = "portable_device"
    SERIAL_PORT = "serial_port"
    USB_STORAGE = "usb_storage"
    PRINTER_DEVICE = "printer_device"
    MONITOR = "monitor"
    SENSOR = "sensor"
    MODEM = "modem"
    USB_OTHER = "usb_other"
    HID_OTHER = "hid_other"
    # 2.2.0
    TOUCHPAD = "touchpad"
    WIRELESS_RECEIVER = "wireless_receiver"  # receptor USB de teclado o mouse inalámbrico
    GAME_CONTROLLER = "game_controller"


class PeripheralConnection(StrEnum):
    USB = "usb"
    BLUETOOTH = "bluetooth"
    INTERNAL = "internal"  # ACPI, PCI, audio integrado, I2C
    VIRTUAL = "virtual"  # dispositivos de software
    OTHER = "other"
    VIDEO = "video"  # monitor por cable de video (HDMI, DisplayPort, USB-C)


class PeripheralFunction(StrEnum):
    """Lo que hace un aparato. Uno solo puede tener varias: teclado con mouse y teclas
    multimedia, cámara con su interfaz de actualización."""

    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    TOUCHPAD = "touchpad"
    MEDIA_KEYS = "media_keys"
    SYSTEM_CONTROL = "system_control"  # botones de encendido o suspensión
    LIGHTING = "lighting"  # iluminación RGB
    GAME_CONTROLLER = "game_controller"
    CAMERA = "camera"
    SCANNER = "scanner"
    FIRMWARE_UPDATE = "firmware_update"
    MICROPHONE = "microphone"
    SPEAKERS = "speakers"
    HEADPHONES = "headphones"
    AUDIO = "audio"
    FINGERPRINT = "fingerprint"
    DISPLAY = "display"
    STORAGE = "storage"
    PORTABLE = "portable"  # teléfono o reproductor
    PRINTER = "printer"
    BLUETOOTH_RADIO = "bluetooth_radio"
    SMART_CARD = "smart_card"
    SERIAL = "serial"
    SENSOR = "sensor"


class PeripheralPart(Model):
    """Un nodo de Windows que forma parte del aparato (detalle técnico)."""

    instance_id: str
    name: str | None = None
    pnp_class: str | None = None
    present: bool = True
    driver_inf: str | None = None


class DisconnectedState(StrEnum):
    # Emparejado por Bluetooth, apagado o lejos: quitarlo lo desempareja.
    PAIRED = "paired"
    # Conectado alguna vez y ya no: Windows lo vuelve a crear si se conecta de nuevo.
    LEFTOVER = "leftover"


class DisconnectedPeripheral(Model):
    """Un aparato que Windows recuerda pero que no está conectado."""

    name: str | None
    generic_name: bool = False
    category: PeripheralCategory
    connection: PeripheralConnection
    functions: list[PeripheralFunction] = Field(default_factory=list)
    state: DisconnectedState
    vendor_id: str | None = None
    product_id: str | None = None
    vendor_name: str | None = None
    container_id: str | None = None
    last_seen_at: datetime | None = None
    # El mismo aparato (fabricante y producto) está conectado ahora en otro puerto.
    also_connected: bool = False
    # Controladores de terceros (oem*.inf) que conviene respaldar antes de quitarlo.
    driver_infs: list[str] = Field(default_factory=list)
    parts: list[PeripheralPart] = Field(default_factory=list)


class Peripheral(Model):
    name: Observed[str]
    category: PeripheralCategory
    connection: PeripheralConnection
    manufacturer: Observed[str]
    vendor_name: Observed[str]
    vendor_id: str | None = None
    product_id: str | None = None
    serial_number: Observed[str]
    instance_id: str | None
    driver_provider: Observed[str]
    driver_version: Observed[str]
    driver_date: Observed[datetime]
    status: Observed[str]
    error_code: int = 0
    error_description: str | None = None
    # 2.2.0: el aparato físico con todas sus funciones (antes, una fila por función de Windows).
    generic_name: bool = False  # el nombre es genérico de Windows; se muestra la función
    functions: list[PeripheralFunction] = Field(default_factory=list)
    container_id: str | None = None
    last_connected_at: datetime | None = None
    parts: list[PeripheralPart] = Field(default_factory=list)


class PeripheralsSection(Model):
    printers: list[Printer]
    devices: list[Peripheral]
    default_printer: str | None = None
    # 2.2.0: aparatos que Windows recuerda pero no están conectados.
    disconnected: list[DisconnectedPeripheral] = Field(default_factory=list)


class SecurityProduct(Model):
    name: Observed[str]
    enabled: Observed[bool]
    up_to_date: Observed[bool]
    executable_path: Observed[str]


class DefenderStatus(Model):
    antivirus_enabled: Observed[bool]
    real_time_protection: Observed[bool]
    running_mode: Observed[str]
    signature_updated_at: Observed[datetime]


class FirewallProfile(Model):
    name: str
    enabled: Observed[bool]


class VolumeEncryption(Model):
    drive_letter: str
    protection: Observed[str]


class SecuritySection(Model):
    antivirus: list[SecurityProduct]
    antivirus_status: Observed[str]
    defender: DefenderStatus | None
    firewall_profiles: list[FirewallProfile]
    secure_boot_enabled: Observed[bool]
    virtualization_based_security: Observed[str]
    memory_integrity_running: Observed[bool]
    code_integrity_policy: Observed[str]
    uac_enabled: Observed[bool]
    powershell_language_mode: Observed[str]
    volume_encryption: list[VolumeEncryption]
    volume_encryption_status: Observed[str]


# --- Documento --------------------------------------------------------------------------------


class SchemaInfo(Model):
    name: str = SCHEMA_NAME
    version: str = SCHEMA_VERSION


class CollectionInfo(Model):
    inventory_id: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    app_version: str
    app_commit: str | None
    status: CollectionStatus
    is_elevated: Observed[bool]
    # Identidad estable del equipo (ver domain/identity.py) y posición en su historial.
    device_key: str
    identity_basis: str
    # Lo asigna el almacén al guardar: un análisis recién hecho aún no tiene número de versión.
    sequence: int | None = Field(default=None, ge=1)
    previous_inventory_id: str | None = None


class HardwareSection(Model):
    processor: ProcessorSection | None
    memory: MemorySection | None
    storage: StorageSection | None
    graphics: GraphicsSection | None
    displays: DisplaySection | None
    network: NetworkSection | None
    battery: BatterySection | None
    tpm: TpmSection | None


class Inventory(Model):
    """Una sección nula significa que su módulo falló: el motivo está en `modules` y `errors`."""

    schema_info: SchemaInfo = Field(default_factory=SchemaInfo, alias="schema")
    collection: CollectionInfo
    device: DeviceIdentity | None
    hardware: HardwareSection
    operating_system: OperatingSystem | None
    software: SoftwareSection | None
    devices: DevicesSection | None
    peripherals: PeripheralsSection | None
    security: SecuritySection | None
    modules: list[ModuleReport]
    warnings: list[Issue]
    errors: list[Issue]
    # Archivos binarios del análisis (iconos), fuera del JSON. Viajan con el objeto hasta guardarlo.
    _attachments: dict[str, bytes] = PrivateAttr(default_factory=dict)

    @property
    def attachments(self) -> dict[str, bytes]:
        return self._attachments

    def with_attachments(self, attachments: dict[str, bytes]) -> Inventory:
        self._attachments = dict(attachments)
        return self

    def to_document(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)
