// Fichas de detalle del hardware, a partir del inventario.

import type {
  Battery,
  DeviceIdentity,
  MemorySection,
  Processor,
  TpmSection,
} from '@/application'
import {
  DEVICE_TYPES,
  FIRMWARE_MODES,
  MEMBERSHIP_KINDS,
  formatBool,
  formatBytes,
  formatDay,
  formatGhz,
  formatKib,
  formatMwh,
  formatPercent,
  spec,
  specText,
} from '@/presentation/shared/formatters'
import type { SpecRow } from '@/presentation/shared/types'

const joined = (...parts: (string | null)[]) =>
  parts.filter(Boolean).join(' ') || null

export function identitySpecs(device: DeviceIdentity): readonly SpecRow[] {
  const membership = device.membership.name.value
  const kind = device.membership.kind.value
  return [
    spec('Nombre del equipo', device.hostname),
    spec('Fabricante', device.manufacturer),
    spec('Modelo', device.model),
    spec('Número de serie', device.serialNumber),
    spec('Tipo', device.deviceType, (value) => DEVICE_TYPES[value] ?? value),
    spec('Arquitectura', device.systemArchitecture),
    specText(
      'Placa base',
      joined(
        device.baseboard.manufacturer.value,
        device.baseboard.product.value,
      ),
    ),
    spec('Serie de la placa', device.baseboard.serialNumber),
    specText(
      'Firmware',
      joined(device.firmware.vendor.value, device.firmware.version.value),
    ),
    spec(
      'Modo de firmware',
      device.firmware.mode,
      (value) => FIRMWARE_MODES[value] ?? value,
    ),
    spec('Fecha del firmware', device.firmware.releaseDate, formatDay),
    spec('SMBIOS', device.firmware.smbiosVersion),
    specText(
      'Dominio o grupo',
      membership
        ? `${membership} (${MEMBERSHIP_KINDS[kind ?? ''] ?? 'pertenencia sin dato'})`
        : null,
    ),
    spec('Etiqueta de activo', device.assetTag),
    spec('UUID', device.systemUuid),
  ]
}

export function processorSpecs(cpu: Processor): readonly SpecRow[] {
  return [
    spec('Modelo', cpu.model),
    spec('Fabricante', cpu.manufacturer),
    spec('Arquitectura', cpu.architecture),
    spec('Núcleos físicos', cpu.physicalCores),
    spec('Procesadores lógicos', cpu.logicalProcessors),
    spec('Frecuencia reportada', cpu.maxFrequencyMhz, formatGhz),
    spec('Zócalo', cpu.socket),
    spec('Caché L2', cpu.l2CacheKib, formatKib),
    spec('Caché L3', cpu.l3CacheKib, formatKib),
    spec(
      'Virtualización en firmware',
      cpu.virtualizationFirmwareEnabled,
      formatBool,
    ),
  ]
}

export function memorySpecs(memory: MemorySection): readonly SpecRow[] {
  return [
    spec('Instalada', memory.installedBytes, formatBytes),
    spec('Visible para Windows', memory.visibleToOsBytes, formatBytes),
    specText('Módulos', String(memory.moduleCount)),
    spec('Ranuras totales', memory.totalSlots),
    spec('Ranuras libres', memory.freeSlots),
  ]
}

export function batterySpecs(battery: Battery): readonly SpecRow[] {
  return [
    spec('Nombre', battery.name),
    spec('Carga', battery.chargePercent, formatPercent),
    spec('Salud', battery.healthPercent, formatPercent),
    spec('Capacidad de diseño', battery.designCapacityMwh, formatMwh),
    spec('Capacidad a plena carga', battery.fullChargeCapacityMwh, formatMwh),
    spec('Ciclos', battery.cycleCount),
  ]
}

export function tpmSpecs(tpm: TpmSection): readonly SpecRow[] {
  return [
    spec('Presente', tpm.present, formatBool),
    spec('Versión', tpm.specVersion),
    spec('Fabricante', tpm.manufacturer),
    spec('Firmware', tpm.firmwareVersion),
    spec('Habilitado', tpm.enabled, formatBool),
    spec('Activado', tpm.activated, formatBool),
  ]
}
