// Contrato del inventario (schema/inventory-2.0.0.schema.json). Cada dato dice cuánto se confía en él.

export type Confidence =
  'verified' | 'reported' | 'inferred' | 'probable' | 'unknown'

export interface Observed<T> {
  readonly value: T | null
  readonly confidence: Confidence
  readonly source: string | null
  readonly reason: string | null
  readonly raw: string | null
}

export type PathState =
  'valid' | 'missing' | 'inaccessible' | 'not_provided' | 'not_checked'

export interface PathEvidence {
  readonly value: string | null
  readonly confidence: Confidence
  readonly source: string | null
  readonly state: PathState
  readonly reason: string | null
}

export interface Issue {
  readonly module: string
  readonly code: string
  readonly message: string
  readonly source: string | null
}

export type ModuleStatus =
  'pending' | 'running' | 'ok' | 'partial' | 'failed' | 'timeout' | 'cancelled'

export interface ModuleReport {
  readonly name: string
  readonly status: ModuleStatus
  readonly durationMs: number
  readonly retries: number
}

// --- Equipo -------------------------------------------------------------------------------------

export type DeviceType =
  | 'desktop'
  | 'laptop'
  | 'tablet'
  | 'all_in_one'
  | 'mini_pc'
  | 'server'
  | 'workstation'
  | 'virtual_machine'
  | 'other'

export interface DeviceIdentity {
  readonly hostname: Observed<string>
  readonly manufacturer: Observed<string>
  readonly model: Observed<string>
  readonly serialNumber: Observed<string>
  readonly systemUuid: Observed<string>
  readonly sku: Observed<string>
  readonly assetTag: Observed<string>
  readonly deviceType: Observed<DeviceType>
  readonly systemArchitecture: Observed<string>
  readonly baseboard: {
    readonly manufacturer: Observed<string>
    readonly product: Observed<string>
    readonly serialNumber: Observed<string>
    readonly version: Observed<string>
  }
  readonly firmware: {
    readonly vendor: Observed<string>
    readonly version: Observed<string>
    readonly smbiosVersion: Observed<string>
    readonly releaseDate: Observed<string>
    readonly mode: Observed<string>
  }
  readonly membership: {
    readonly kind: Observed<string>
    readonly name: Observed<string>
  }
}

// --- Hardware -----------------------------------------------------------------------------------

export interface Processor {
  readonly manufacturer: Observed<string>
  readonly model: Observed<string>
  readonly architecture: Observed<string>
  readonly physicalCores: Observed<number>
  readonly logicalProcessors: Observed<number>
  readonly maxFrequencyMhz: Observed<number>
  readonly socket: Observed<string>
  readonly addressWidthBits: Observed<number>
  readonly l2CacheKib: Observed<number>
  readonly l3CacheKib: Observed<number>
  readonly virtualizationFirmwareEnabled: Observed<boolean>
}

export interface MemoryModule {
  readonly capacityBytes: Observed<number>
  readonly memoryType: Observed<string>
  readonly speedMts: Observed<number>
  readonly configuredSpeedMts: Observed<number>
  readonly manufacturer: Observed<string>
  readonly partNumber: Observed<string>
  readonly serialNumber: Observed<string>
  readonly slot: Observed<string>
  readonly bank: Observed<string>
  readonly formFactor: Observed<string>
}

export interface MemorySection {
  readonly installedBytes: Observed<number>
  readonly visibleToOsBytes: Observed<number>
  readonly moduleCount: number
  readonly modules: readonly MemoryModule[]
  readonly totalSlots: Observed<number>
  readonly freeSlots: Observed<number>
}

export type DiskKind =
  'hdd' | 'ssd_sata' | 'ssd_nvme' | 'ssd_sas' | 'ssd_other' | 'emmc'

export interface Volume {
  readonly driveLetter: string | null
  readonly label: string | null
  readonly fileSystem: string | null
  readonly sizeBytes: Observed<number>
  readonly freeBytes: Observed<number>
  readonly usedBytes: Observed<number>
}

export interface Partition {
  readonly number: number
  readonly driveLetter: string | null
  readonly sizeBytes: Observed<number>
  readonly kind: string | null
  readonly volume: Volume | null
}

export interface PhysicalDisk {
  readonly number: Observed<number>
  readonly manufacturer: Observed<string>
  readonly model: Observed<string>
  readonly serialNumber: Observed<string>
  readonly capacityBytes: Observed<number>
  readonly kind: Observed<DiskKind>
  readonly bus: string
  readonly isBootDisk: Observed<boolean>
  readonly health: Observed<string>
  readonly partitions: readonly Partition[]
  /** 2.2.0: marca de la controladora cuando Windows no da la del disco. */
  readonly controllerVendor?: string | null
}

export interface ExcludedDisk {
  readonly model: string | null
  readonly bus: string
  readonly reason: string
}

export interface StorageSection {
  readonly disks: readonly PhysicalDisk[]
  readonly excluded: readonly ExcludedDisk[]
  readonly detectionSource: string
  /** 2.2.0: discos USB, tarjetas y FireWire conectados al analizar. */
  readonly external?: readonly PhysicalDisk[]
}

export interface GraphicsAdapter {
  readonly name: Observed<string>
  readonly vendor: Observed<string>
  readonly driverVersion: Observed<string>
  readonly driverDate: Observed<string>
  readonly memoryBytes: Observed<number>
  readonly currentWidthPixels: Observed<number>
  readonly currentHeightPixels: Observed<number>
  readonly currentRefreshHz: Observed<number>
  readonly status: Observed<string>
}

export interface Monitor {
  readonly manufacturerCode: Observed<string>
  readonly model: Observed<string>
  readonly serialNumber: Observed<string>
  readonly yearOfManufacture: Observed<number>
  readonly isActive: Observed<boolean>
}

export interface DisplayMode {
  readonly device: string
  readonly isPrimary: boolean
  readonly widthPixels: number
  readonly heightPixels: number
  readonly refreshHz: number | null
}

export interface NetworkAdapter {
  readonly name: Observed<string>
  readonly description: Observed<string>
  readonly manufacturer: Observed<string>
  readonly macAddress: Observed<string>
  readonly connection: Observed<string>
  readonly linkSpeedBitsPerSecond: Observed<number>
  readonly driverVersion: Observed<string>
  readonly ipv4Addresses: readonly string[]
}

export interface Battery {
  readonly name: Observed<string>
  readonly manufacturer: Observed<string>
  readonly chemistry: Observed<string>
  readonly chargePercent: Observed<number>
  readonly status: Observed<string>
  readonly designCapacityMwh: Observed<number>
  readonly fullChargeCapacityMwh: Observed<number>
  readonly healthPercent: Observed<number>
  readonly cycleCount: Observed<number>
}

export interface TpmSection {
  readonly present: Observed<boolean>
  readonly specVersion: Observed<string>
  readonly manufacturer: Observed<string>
  readonly firmwareVersion: Observed<string>
  readonly enabled: Observed<boolean>
  readonly activated: Observed<boolean>
}

export interface Hardware {
  readonly processor: {
    readonly processors: readonly Processor[]
    readonly totalPhysicalCores: Observed<number>
    readonly totalLogicalProcessors: Observed<number>
  } | null
  readonly memory: MemorySection | null
  readonly storage: StorageSection | null
  readonly graphics: { readonly adapters: readonly GraphicsAdapter[] } | null
  readonly displays: {
    readonly monitors: readonly Monitor[]
    readonly activeModes: readonly DisplayMode[]
  } | null
  readonly network: {
    readonly adapters: readonly NetworkAdapter[]
    readonly detectionSource: string
  } | null
  readonly battery: {
    readonly present: boolean
    readonly batteries: readonly Battery[]
  } | null
  readonly tpm: TpmSection | null
}

// --- Sistema ------------------------------------------------------------------------------------

export interface HotFix {
  readonly id: string
  readonly description: string | null
  readonly installedOnRaw: string | null
}

export interface OperatingSystem {
  readonly name: Observed<string>
  readonly generation: Observed<string>
  readonly editionId: Observed<string>
  readonly isLtsc: Observed<boolean>
  readonly displayVersion: Observed<string>
  readonly version: Observed<string>
  readonly build: Observed<number>
  readonly ubr: Observed<number>
  readonly fullBuild: Observed<string>
  readonly architecture: Observed<string>
  readonly installedAt: Observed<string>
  readonly lastBootAt: Observed<string>
  readonly locale: Observed<string>
  readonly hotfixCount: Observed<number>
  readonly hotfixes: readonly HotFix[]
}

// --- Software -----------------------------------------------------------------------------------

export type SignatureStatus =
  | 'valid'
  | 'not_signed'
  | 'hash_mismatch'
  | 'not_trusted'
  | 'unknown_error'
  | 'not_supported'
  | 'not_checked'

export type InstallerType = 'msi' | 'traditional' | 'msix' | 'other' | 'unknown'
export type SoftwareScope = 'machine' | 'current_user'

export interface SoftwareItem {
  readonly id: string
  readonly name: string
  readonly version: Observed<string>
  readonly publisher: Observed<string>
  readonly scope: SoftwareScope
  readonly installerType: InstallerType
  readonly mechanism: string
  readonly detectionSource: string
  readonly installPath: PathEvidence
  readonly executablePath: PathEvidence
  readonly uninstall: {
    readonly command: string | null
    readonly path: PathEvidence
  } | null
  readonly installDate: Observed<string>
  readonly architecture: Observed<string>
  readonly sizeBytes: Observed<number>
  readonly executable: {
    readonly fileVersion: string | null
    readonly productVersion: string | null
    readonly productName: string | null
    readonly fileDescription: string | null
    readonly companyName: string | null
    readonly signature: {
      readonly status: SignatureStatus
      readonly signer: string | null
      readonly reason: string | null
    }
  } | null
  readonly packageFullName: string | null
  readonly packageSignatureKind: string | null
  readonly isSystemComponent: boolean
  readonly isFramework: boolean
  readonly isUpdate: boolean
  readonly iconId: string | null
}

export type SoftwareSourceStatus =
  'ok' | 'not_present' | 'access_denied' | 'failed'

export interface SoftwareSection {
  readonly items: readonly SoftwareItem[]
  readonly totalCount: number
  readonly executableResolvedCount: number
  readonly signatureCheckedCount: number
  readonly skippedEntriesWithoutName: number
  readonly sources: readonly {
    readonly source: string
    readonly status: SoftwareSourceStatus
    readonly itemCount: number
    readonly detail: string | null
  }[]
  readonly limitations: readonly string[]
}

/** Lo que el técnico ve por defecto: sin componentes del sistema, marcos ni actualizaciones. */
export function isUserFacingSoftware(item: SoftwareItem): boolean {
  return !(item.isSystemComponent || item.isFramework || item.isUpdate)
}

// --- Dispositivos y seguridad -------------------------------------------------------------------

export interface ProblemDevice {
  readonly name: Observed<string>
  readonly deviceClass: Observed<string>
  readonly manufacturer: Observed<string>
  readonly deviceId: string | null
  readonly errorCode: number
  readonly errorDescription: string | null
  readonly status: Observed<string>
}

export interface SecurityProduct {
  readonly name: Observed<string>
  readonly enabled: Observed<boolean>
  readonly upToDate: Observed<boolean>
  readonly executablePath: Observed<string>
}

export interface SecuritySection {
  readonly antivirus: readonly SecurityProduct[]
  readonly antivirusStatus: Observed<string>
  readonly defender: {
    readonly antivirusEnabled: Observed<boolean>
    readonly realTimeProtection: Observed<boolean>
    readonly runningMode: Observed<string>
    readonly signatureUpdatedAt: Observed<string>
  } | null
  readonly firewallProfiles: readonly {
    readonly name: string
    readonly enabled: Observed<boolean>
  }[]
  readonly secureBootEnabled: Observed<boolean>
  readonly virtualizationBasedSecurity: Observed<string>
  readonly memoryIntegrityRunning: Observed<boolean>
  readonly codeIntegrityPolicy: Observed<string>
  readonly uacEnabled: Observed<boolean>
  readonly powershellLanguageMode: Observed<string>
  readonly volumeEncryption: readonly {
    readonly driveLetter: string
    readonly protection: Observed<string>
  }[]
  readonly volumeEncryptionStatus: Observed<string>
}

// --- Periféricos e impresoras -------------------------------------------------------------------

export type PrinterConnection =
  'network_tcp' | 'wsd' | 'ipp' | 'usb' | 'shared' | 'virtual' | 'local_other'

export interface Printer {
  readonly name: string
  readonly driverName: Observed<string>
  readonly manufacturer: Observed<string>
  readonly driverVersion: Observed<string>
  readonly portName: Observed<string>
  readonly connection: PrinterConnection
  readonly hostAddress: Observed<string>
  readonly portNumber: Observed<number>
  readonly protocol: Observed<string>
  readonly isDefault: Observed<boolean>
  readonly isShared: Observed<boolean>
  readonly shareName: Observed<string>
  readonly status: Observed<string>
  readonly detectedError: Observed<string>
  readonly location: Observed<string>
  readonly comment: Observed<string>
  readonly serialNumber: Observed<string>
  readonly usbVendorId: string | null
  readonly usbProductId: string | null
  readonly queuedJobs: Observed<number>
}

export type PeripheralCategory =
  | 'keyboard'
  | 'mouse'
  | 'camera'
  | 'imaging'
  | 'audio'
  | 'audio_endpoint'
  | 'bluetooth'
  | 'smart_card_reader'
  | 'smart_card'
  | 'biometric'
  | 'portable_device'
  | 'serial_port'
  | 'usb_storage'
  | 'printer_device'
  | 'monitor'
  | 'sensor'
  | 'modem'
  | 'usb_other'
  | 'hid_other'
  | 'touchpad'
  | 'wireless_receiver'
  | 'game_controller'

export type PeripheralConnection =
  'usb' | 'bluetooth' | 'internal' | 'virtual' | 'other' | 'video'

/** Lo que hace un aparato; uno solo puede tener varias (teclado con mouse). */
export type PeripheralFunction = string

/** Un nodo de Windows que forma parte del aparato (detalle técnico). */
export interface PeripheralPart {
  readonly instanceId: string
  readonly name: string | null
  readonly pnpClass: string | null
  readonly present: boolean
  readonly driverInf: string | null
}

/** Un aparato que Windows recuerda sin estar conectado. */
export interface DisconnectedPeripheral {
  readonly name: string | null
  readonly genericName: boolean
  readonly category: PeripheralCategory
  readonly connection: PeripheralConnection
  readonly functions: readonly PeripheralFunction[]
  /** `paired`: emparejado por Bluetooth; `leftover`: conectado alguna vez y ya no. */
  readonly state: 'paired' | 'leftover'
  readonly vendorId: string | null
  readonly productId: string | null
  readonly vendorName: string | null
  readonly containerId: string | null
  readonly lastSeenAt: string | null
  /** El mismo aparato está conectado ahora en otro puerto. */
  readonly alsoConnected: boolean
  readonly driverInfs: readonly string[]
  readonly parts: readonly PeripheralPart[]
}

export interface Peripheral {
  readonly name: Observed<string>
  readonly category: PeripheralCategory
  readonly connection: PeripheralConnection
  readonly manufacturer: Observed<string>
  readonly vendorName: Observed<string>
  readonly vendorId: string | null
  readonly productId: string | null
  readonly serialNumber: Observed<string>
  readonly instanceId: string | null
  readonly driverProvider: Observed<string>
  readonly driverVersion: Observed<string>
  readonly driverDate: Observed<string>
  readonly status: Observed<string>
  readonly errorCode: number
  readonly errorDescription: string | null
  /** 2.2.0: el nombre es genérico de Windows; se muestra la función. */
  readonly genericName?: boolean
  readonly functions?: readonly PeripheralFunction[]
  readonly containerId?: string | null
  readonly lastConnectedAt?: string | null
  readonly parts?: readonly PeripheralPart[]
}

export interface PeripheralsSection {
  readonly printers: readonly Printer[]
  readonly devices: readonly Peripheral[]
  readonly defaultPrinter: string | null
  /** 2.2.0: aparatos que Windows recuerda sin estar conectados. */
  readonly disconnected?: readonly DisconnectedPeripheral[]
}

/** Los componentes HID genéricos de un dispositivo se ocultan salvo que se pidan. */
export function isDetailComponent(device: Peripheral): boolean {
  // Desde 2.2.0 cada fila es un aparato completo: solo los inventarios anteriores traen las
  // funciones HID sueltas.
  return device.category === 'hid_other' && device.functions === undefined
}

// --- Documento ----------------------------------------------------------------------------------

export interface Inventory {
  readonly schema: { readonly name: string; readonly version: string }
  readonly collection: {
    readonly inventoryId: string
    readonly startedAt: string
    readonly finishedAt: string
    readonly durationMs: number
    readonly appVersion: string
    readonly appCommit: string | null
    readonly status: 'complete' | 'partial'
    readonly isElevated: Observed<boolean>
    readonly deviceKey: string
    readonly identityBasis: string
    readonly sequence: number | null
    readonly previousInventoryId: string | null
  }
  readonly device: DeviceIdentity | null
  readonly hardware: Hardware
  readonly operatingSystem: OperatingSystem | null
  readonly software: SoftwareSection | null
  readonly devices: {
    readonly totalCount: Observed<number>
    readonly problemCount: number
    readonly problems: readonly ProblemDevice[]
  } | null
  readonly peripherals: PeripheralsSection | null
  readonly security: SecuritySection | null
  readonly modules: readonly ModuleReport[]
  readonly warnings: readonly Issue[]
  readonly errors: readonly Issue[]
}
