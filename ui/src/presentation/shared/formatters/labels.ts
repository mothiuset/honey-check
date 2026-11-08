// Vocabulario de la interfaz: los códigos estables del contrato traducidos al técnico.

export const MODULE_STATUS: Record<string, string> = {
  pending: 'pendiente',
  running: 'leyendo',
  ok: 'completo',
  partial: 'parcial',
  failed: 'falló',
  timeout: 'sin respuesta',
  cancelled: 'cancelado',
}

export const MODULE_LABELS: Record<string, string> = {
  identity: 'Identidad',
  processor: 'Procesador',
  memory: 'Memoria',
  storage: 'Discos',
  operating_system: 'Sistema',
  graphics: 'Gráficos',
  displays: 'Pantallas',
  network: 'Red',
  battery: 'Batería',
  tpm: 'TPM',
  devices: 'Dispositivos',
  peripherals: 'Periféricos',
  security: 'Seguridad',
  software: 'Software',
}

export const REASONS: Record<string, string> = {
  requires_snmp_query: 'se consulta a la impresora por SNMP',
  not_reported_by_windows: 'Windows no lo informa',
  placeholder_value: 'el fabricante dejó un valor de relleno',
  access_denied: 'requiere administrador',
  query_failed: 'la consulta falló',
  not_available_on_this_system: 'no disponible en este equipo',
  invalid_value: 'valor no válido',
  not_applicable: 'no aplica',
  not_resolved: 'no se pudo verificar',
  not_checked: 'sin comprobar',
  media_type_unspecified: 'Windows no indica si es HDD o SSD',
  win32_diskdrive_has_no_media_type: 'esta fuente no distingue HDD de SSD',
  adapter_ram_saturated_32bit: 'Windows limita este dato a 4 GiB',
  install_location_not_reported: 'el programa no declara su carpeta',
  windows_does_not_identify_executable: 'Windows no identifica un ejecutable',
  no_unambiguous_executable_in_install_path:
    'hay varios candidatos y ninguno es claro',
  display_icon_is_not_the_main_executable:
    'el icono registrado no es el programa',
  install_path_missing_on_disk: 'la carpeta declarada no existe',
  install_path_inaccessible: 'la carpeta declarada no es accesible',
  package_manifest_not_readable: 'no se pudo leer el manifiesto del paquete',
  package_declares_no_executable: 'el paquete no declara un ejecutable',
  package_without_install_location: 'el paquete no declara su carpeta',
  time_budget_exhausted: 'se agotó el tiempo disponible',
  package_signature_reported_instead: 'se informa la firma del paquete',
  file_not_accessible: 'el archivo no es accesible',
  invalid_json: 'el archivo está dañado',
  schema_validation_failed: 'el archivo no cumple el formato',
}

export const CONFIDENCE_TAGS: Record<string, [string, string]> = {
  verified: ['verificado', 'Comprobado contra el propio archivo.'],
  inferred: [
    'calculado',
    'Calculado con una regla a partir de datos de Windows.',
  ],
  probable: ['probable', 'Candidato deducido: puede no ser correcto.'],
}

export const DEVICE_TYPES: Record<string, string> = {
  desktop: 'Escritorio',
  laptop: 'Portátil',
  tablet: 'Tableta',
  all_in_one: 'Todo en uno',
  mini_pc: 'Mini PC',
  server: 'Servidor',
  workstation: 'Estación de trabajo',
  virtual_machine: 'Máquina virtual',
  other: 'Otro',
}

export const DISK_KINDS: Record<string, string> = {
  hdd: 'HDD',
  ssd_sata: 'SSD SATA',
  ssd_nvme: 'SSD NVMe',
  ssd_sas: 'SSD SAS',
  ssd_other: 'SSD',
  emmc: 'eMMC',
}

export const EXCLUSIONS: Record<string, string> = {
  external_usb: 'USB externo',
  removable_card: 'tarjeta extraíble',
  external_firewire: 'FireWire externo',
  virtual_disk: 'disco virtual',
  storage_spaces_virtual_disk: 'disco virtual de Espacios de almacenamiento',
  network_storage: 'almacenamiento de red',
  removable_media: 'medio extraíble',
}

export const INSTALLERS: Record<string, string> = {
  msi: 'MSI',
  traditional: 'Instalador tradicional',
  msix: 'Microsoft Store/MSIX',
  other: 'Otro',
  unknown: 'Sin determinar',
}

export const SCOPES: Record<string, string> = {
  machine: 'Todo el equipo',
  current_user: 'Usuario actual',
}

export const PATH_STATES: Record<string, string> = {
  valid: 'existe',
  missing: 'no existe',
  inaccessible: 'sin acceso',
  not_checked: 'no comprobada',
}

export const SIGNATURES: Record<string, string> = {
  valid: 'Firma válida',
  not_signed: 'Sin firma',
  hash_mismatch: 'Firma alterada',
  not_trusted: 'Firma no confiable',
  unknown_error: 'No se pudo verificar',
  not_supported: 'Formato sin firma',
  not_checked: 'Sin comprobar',
}

export const STATUS_LABELS: Record<string, string> = {
  complete: 'Completo',
  partial: 'Parcial',
}

export const AREAS: Record<string, string> = {
  device: 'Equipo',
  processor: 'Procesador',
  memory: 'Memoria',
  storage: 'Almacenamiento',
  graphics: 'Gráficos',
  tpm: 'TPM',
  operating_system: 'Sistema operativo',
  security: 'Seguridad',
  software: 'Software',
}

// Datos de la comparación, por área y campo del contrato.
export const COMPARE_FIELDS: Record<string, string> = {
  'device.hostname': 'Nombre del equipo',
  'device.manufacturer': 'Fabricante',
  'device.model': 'Modelo',
  'device.serial_number': 'Número de serie',
  'device.device_type': 'Tipo de equipo',
  'device.asset_tag': 'Etiqueta de activo',
  'device.baseboard': 'Placa base',
  'device.firmware_version': 'Versión del firmware',
  'device.firmware_mode': 'Modo de firmware',
  'device.domain': 'Dominio o grupo',
  'processor.processor': 'Procesador',
  'processor.cores': 'Núcleos físicos',
  'processor.logical_processors': 'Procesadores lógicos',
  'memory.installed_bytes': 'Memoria instalada',
  'memory.total_slots': 'Ranuras de memoria',
  'memory.module': 'Módulo de memoria',
  'storage.disk': 'Unidad',
  'graphics.adapter': 'Tarjeta gráfica',
  'tpm.present': 'TPM presente',
  'tpm.spec_version': 'Versión del TPM',
  'operating_system.name': 'Sistema operativo',
  'operating_system.edition_id': 'Edición',
  'operating_system.display_version': 'Versión',
  'operating_system.full_build': 'Compilación',
  'operating_system.architecture': 'Arquitectura',
  'operating_system.installed_at': 'Instalado',
  'security.secure_boot_enabled': 'Arranque seguro',
  'security.uac_enabled': 'Control de cuentas (UAC)',
  'security.memory_integrity_running': 'Integridad de memoria',
  'security.code_integrity_policy': 'Integridad de código',
  'security.powershell_language_mode': 'Modo de lenguaje de PowerShell',
}

export function reasonText(reason: string | null | undefined): string {
  if (!reason) return ''
  return REASONS[reason] ?? reason.replaceAll('_', ' ')
}

export const SOURCE_STATUS: Record<string, string> = {
  ok: 'Leída',
  not_present: 'No existe',
  access_denied: 'Sin permisos',
  failed: 'Falló',
}

export const OS_GENERATIONS: Record<string, string> = {
  windows_10: 'Windows 10',
  windows_11: 'Windows 11',
  other: 'Otra',
}

export const VBS_STATES: Record<string, string> = {
  disabled: 'Deshabilitada',
  enabled_not_running: 'Habilitada, sin ejecutarse',
  running: 'En ejecución',
}

export const CODE_INTEGRITY: Record<string, string> = {
  off: 'Desactivada',
  audit: 'Auditoría',
  enforced: 'Aplicada',
}

/** Particiones que Windows reserva para arrancar y recuperarse. */
export const PARTITION_KINDS: Record<string, string> = {
  efi_system: 'Arranque (EFI)',
  recovery: 'Recuperación de Windows',
  microsoft_reserved: 'Reservada por Windows',
  basic_data: 'Datos',
  other_gpt: 'Otra',
}

export const DISK_HEALTH: Record<string, string> = {
  healthy: 'Correcto',
  warning: 'Advertencia',
  unhealthy: 'Con fallos',
}

export const FIRMWARE_MODES: Record<string, string> = {
  uefi: 'UEFI',
  bios: 'BIOS heredado',
}

export const MEMBERSHIP_KINDS: Record<string, string> = {
  domain: 'dominio',
  workgroup: 'grupo de trabajo',
}

export const PRINTER_CONNECTIONS: Record<string, string> = {
  network_tcp: 'Red (TCP/IP)',
  wsd: 'Red (WSD)',
  ipp: 'Red (IPP / universal)',
  usb: 'USB',
  shared: 'Compartida de otro equipo',
  virtual: 'Virtual',
  local_other: 'Puerto local',
}

export const PRINTER_STATUS: Record<string, string> = {
  idle: 'Lista',
  printing: 'Imprimiendo',
  warming_up: 'Calentando',
  stopped: 'Detenida',
  offline: 'Sin conexión',
  other: 'Otro',
  unknown: 'Desconocido',
}

export const PRINTER_ERRORS: Record<string, string> = {
  low_paper: 'Poco papel',
  no_paper: 'Sin papel',
  low_toner: 'Poco tóner',
  no_toner: 'Sin tóner',
  door_open: 'Puerta abierta',
  jammed: 'Atasco',
  offline: 'Sin conexión',
  service_requested: 'Requiere servicio',
  output_bin_full: 'Bandeja de salida llena',
}

export const PERIPHERAL_CATEGORIES: Record<string, string> = {
  keyboard: 'Teclados',
  mouse: 'Mouse',
  touchpad: 'Touchpads',
  wireless_receiver: 'Receptores inalámbricos',
  game_controller: 'Controles de juego',
  camera: 'Cámaras',
  imaging: 'Escáneres y cámaras de imagen',
  audio: 'Audio',
  audio_endpoint: 'Salidas y entradas de audio',
  bluetooth: 'Bluetooth',
  smart_card_reader: 'Lectores de tarjetas y tokens',
  smart_card: 'Tarjetas y tokens',
  biometric: 'Biométricos',
  portable_device: 'Teléfonos y dispositivos portátiles',
  serial_port: 'Puertos serie',
  usb_storage: 'Almacenamiento USB',
  printer_device: 'Impresoras conectadas',
  monitor: 'Monitores',
  sensor: 'Sensores',
  modem: 'Módems',
  usb_other: 'Otros USB',
  hid_other: 'Componentes HID',
}

export const PERIPHERAL_CONNECTIONS: Record<string, string> = {
  usb: 'USB',
  bluetooth: 'Bluetooth',
  internal: 'Integrado',
  virtual: 'Software',
  other: 'Otro',
  video: 'Cable de video',
}

/** Lo que hace un aparato, en minúscula para enumerarlo («teclado, mouse»). */
export const PERIPHERAL_FUNCTIONS: Record<string, string> = {
  keyboard: 'teclado',
  mouse: 'mouse',
  touchpad: 'touchpad',
  media_keys: 'teclas multimedia',
  system_control: 'botones de encendido',
  lighting: 'iluminación RGB',
  game_controller: 'control de juego',
  camera: 'cámara',
  scanner: 'escáner',
  firmware_update: 'actualización de firmware',
  microphone: 'micrófono',
  speakers: 'parlantes',
  headphones: 'audífonos',
  audio: 'audio',
  fingerprint: 'lector de huella',
  display: 'pantalla',
  storage: 'almacenamiento',
  portable: 'teléfono o reproductor',
  printer: 'impresora',
  bluetooth_radio: 'adaptador Bluetooth',
  smart_card: 'lector de tarjetas',
  serial: 'puerto serie',
  sensor: 'sensor',
}
