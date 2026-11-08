import type { Inventory } from '@/application'
import {
  DEVICE_TYPES,
  DISK_KINDS,
  formatBytes,
  formatDate,
} from '@/presentation/shared/formatters'
import { hrefOf } from '@/presentation/shared/navigation'
import type { Metric } from '../types/analysis.types'

function storageSummary(inventory: Inventory): string | null {
  const disks = inventory.hardware.storage?.disks ?? []
  if (!disks.length) return null
  return disks
    .map((disk) => {
      const size =
        disk.capacityBytes.value === null
          ? '?'
          : formatBytes(disk.capacityBytes.value)
      return `${size} ${disk.kind.value ? (DISK_KINDS[disk.kind.value] ?? '') : ''}`.trim()
    })
    .join(' + ')
}

/** Datos clave del panel; cada tarjeta lleva a su apartado. */
export function panelMetrics(inventory: Inventory): readonly Metric[] {
  const { device, hardware, operatingSystem, software, collection } = inventory
  const cpu = hardware.processor?.processors[0]
  const memory = hardware.memory
  const type = device?.deviceType.value
  return [
    {
      label: 'Número de serie',
      value: device?.serialNumber.value ?? null,
      href: hrefOf('hardware', 'identificacion'),
    },
    {
      label: 'Tipo de equipo',
      value: type ? (DEVICE_TYPES[type] ?? type) : null,
      href: hrefOf('hardware', 'identificacion'),
    },
    {
      label: 'Procesador',
      value: cpu?.model.value ?? null,
      detail: cpu?.logicalProcessors.value
        ? `${String(cpu.logicalProcessors.value)} procesadores lógicos`
        : null,
      href: hrefOf('hardware', 'procesador'),
    },
    {
      label: 'Memoria',
      value: memory?.installedBytes.value
        ? formatBytes(memory.installedBytes.value)
        : null,
      detail: memory
        ? `${memory.modules[0]?.memoryType.value ?? 'tipo sin dato'}, ${String(memory.moduleCount)} ${memory.moduleCount === 1 ? 'módulo' : 'módulos'}`
        : null,
      href: hrefOf('hardware', 'memoria'),
    },
    {
      label: 'Almacenamiento interno',
      value: storageSummary(inventory),
      href: hrefOf('almacenamiento'),
    },
    {
      label: 'Sistema operativo',
      value: operatingSystem?.name.value ?? null,
      detail: operatingSystem?.fullBuild.value ?? null,
      href: hrefOf('sistema'),
    },
    {
      label: 'Programas registrados',
      value: software ? String(software.totalCount) : null,
      href: hrefOf('software'),
    },
    {
      label: 'Analizado',
      value: formatDate(collection.startedAt),
      detail: collection.sequence
        ? `Versión ${String(collection.sequence)}`
        : null,
      href: hrefOf('equipos'),
    },
  ]
}
