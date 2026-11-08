// Uso de cada volumen de una unidad, con el tono según lo lleno que está.

import type { PhysicalDisk, Volume } from '@/application'
import {
  DISK_HEALTH,
  DISK_KINDS,
  formatBytes,
} from '@/presentation/shared/formatters'
import type { TagTone } from '@/presentation/shared/components'
import type { VolumeUsage } from '../types/analysis.types'

export function usagePercent(volume: Volume | null): number | null {
  const size = volume?.sizeBytes.value
  const used = volume?.usedBytes.value
  if (!size || used === null || used === undefined) return null
  return Math.min(100, (used / size) * 100)
}

const toneOf = (percent: number): VolumeUsage['tone'] =>
  percent >= 90 ? 'bad' : percent >= 75 ? 'warn' : 'ok'

/** Las particiones que el técnico usa: con letra, o de datos con su volumen. */
export const userPartitions = (disk: PhysicalDisk) =>
  disk.partitions.filter(
    (p) => p.driveLetter || (p.volume && (p.kind === 'basic_data' || !p.kind)),
  )

/** Las que Windows reserva (arranque, recuperación): se muestran plegadas. */
export const systemPartitions = (disk: PhysicalDisk) =>
  disk.partitions.filter((p) => !userPartitions(disk).includes(p))

export function volumeUsages(disk: PhysicalDisk): readonly VolumeUsage[] {
  return userPartitions(disk).flatMap((partition) => {
    const volume = partition.volume
    const percent = usagePercent(volume)
    if (!volume || percent === null) return []
    return [
      {
        drive: partition.driveLetter
          ? `${partition.driveLetter}:`
          : 'Sin letra',
        name: volume.label || volume.fileSystem || '',
        free:
          volume.freeBytes.value === null
            ? 'Sin dato'
            : formatBytes(volume.freeBytes.value),
        size:
          volume.sizeBytes.value === null
            ? 'Sin dato'
            : formatBytes(volume.sizeBytes.value),
        percent,
        tone: toneOf(percent),
        letter: partition.driveLetter,
      },
    ]
  })
}

export interface DiskChip {
  readonly label: string
  readonly tone: TagTone
}

export function diskChips(disk: PhysicalDisk): readonly DiskChip[] {
  const health = disk.health.value
  return [
    {
      label: disk.kind.value
        ? (DISK_KINDS[disk.kind.value] ?? disk.kind.value)
        : 'Tipo sin determinar',
      tone: 'neutral',
    },
    { label: disk.bus.toUpperCase().replaceAll('_', ' '), tone: 'neutral' },
    {
      label: health ? (DISK_HEALTH[health] ?? health) : 'Salud sin dato',
      tone: health === 'healthy' ? 'ok' : health ? 'bad' : 'neutral',
    },
    ...(disk.isBootDisk.value
      ? [{ label: 'Arranque', tone: 'honey' as const }]
      : []),
  ]
}
