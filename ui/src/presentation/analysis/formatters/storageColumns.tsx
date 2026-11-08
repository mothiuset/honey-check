import type { ExcludedDisk, Partition } from '@/application'
import { Value, type Column } from '@/presentation/shared/components'
import {
  EXCLUSIONS,
  describeQuiet,
  formatBytes,
  formatNumber,
  PARTITION_KINDS,
} from '@/presentation/shared/formatters'
import { usagePercent } from './storageUsage'

export const partitionColumns: readonly Column<Partition>[] = [
  {
    key: 'drive',
    label: 'Partición',
    value: (p) =>
      p.driveLetter
        ? `${p.driveLetter}:`
        : ((p.kind ? PARTITION_KINDS[p.kind] : null) ?? 'Sin letra'),
  },
  {
    key: 'label',
    label: 'Etiqueta',
    priority: 3,
    value: (p) => p.volume?.label ?? '',
  },
  {
    key: 'fs',
    label: 'Sistema de archivos',
    priority: 3,
    value: (p) => p.volume?.fileSystem ?? 'Sin dato',
  },
  {
    key: 'size',
    label: 'Tamaño',
    align: 'end',
    value: (p) => p.sizeBytes.value,
    render: (p) => <Value display={describeQuiet(p.sizeBytes, formatBytes)} />,
  },
  {
    key: 'free',
    label: 'Libre',
    align: 'end',
    value: (p) => p.volume?.freeBytes.value ?? null,
    render: (p) =>
      p.volume ? (
        <Value display={describeQuiet(p.volume.freeBytes, formatBytes)} />
      ) : null,
  },
  {
    key: 'usage',
    label: 'Uso',
    priority: 2,
    value: (p) => {
      const percent = usagePercent(p.volume)
      return percent === null ? '' : `${formatNumber(percent)} %`
    },
  },
]

export const excludedColumns: readonly Column<ExcludedDisk>[] = [
  { key: 'model', label: 'Modelo', value: (d) => d.model ?? 'Sin modelo' },
  {
    key: 'reason',
    label: 'Motivo',
    value: (d) => EXCLUSIONS[d.reason] ?? d.reason,
  },
]
