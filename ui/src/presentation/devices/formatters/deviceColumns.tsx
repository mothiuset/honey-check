import type { DeviceSummary, InventorySummary } from '@/application'
import type { ReactNode } from 'react'
import { Tag, type Column } from '@/presentation/shared/components'
import {
  STATUS_LABELS,
  formatBytes,
  formatDate,
  reasonText,
} from '@/presentation/shared/formatters'

export const deviceColumns: readonly Column<DeviceSummary>[] = [
  {
    key: 'name',
    label: 'Equipo',
    sortable: true,
    value: (d) => d.hostname ?? 'Equipo sin nombre',
    render: (d) => (
      <>
        {d.hostname ?? 'Equipo sin nombre'}
        {d.isCurrent ? <Tag tone="honey">este equipo</Tag> : null}
      </>
    ),
  },
  {
    key: 'manufacturer',
    label: 'Fabricante y modelo',
    priority: 2,
    sortable: true,
    value: (d) =>
      [d.manufacturer, d.model].filter(Boolean).join(' ') || 'Sin dato',
  },
  {
    key: 'os',
    label: 'Sistema',
    priority: 3,
    sortable: true,
    value: (d) => d.osName ?? 'Sin dato',
  },
  {
    key: 'serial',
    label: 'Serial',
    priority: 3,
    value: (d) => d.serialNumber ?? 'Sin dato',
  },
  {
    key: 'versions',
    label: 'Versiones',
    priority: 2,
    align: 'end',
    sortable: true,
    value: (d) => d.inventoryCount,
  },
  {
    key: 'last',
    label: 'Último análisis',
    sortable: true,
    value: (d) =>
      d.lastCollectedAt ? formatDate(d.lastCollectedAt) : 'Sin dato',
  },
]

export interface VersionColumnOptions {
  readonly referenceId: string | null
  readonly renderActions: (version: InventorySummary) => ReactNode
}

export function versionColumns({
  referenceId,
  renderActions,
}: VersionColumnOptions): readonly Column<InventorySummary>[] {
  return [
    {
      key: 'version',
      label: 'Versión',
      value: (v) => `v${String(v.sequence ?? '?')}`,
      render: (v) => (
        <>
          v{v.sequence ?? '?'}
          {v.id === referenceId ? <Tag tone="honey">referencia</Tag> : null}
        </>
      ),
    },
    {
      key: 'date',
      label: 'Fecha',
      value: (v) => (v.collectedAt ? formatDate(v.collectedAt) : ''),
    },
    {
      key: 'status',
      label: 'Resultado',
      priority: 2,
      value: (v) =>
        v.invalidReason
          ? reasonText(v.invalidReason)
          : (STATUS_LABELS[v.status ?? ''] ?? v.status ?? ''),
    },
    {
      key: 'size',
      label: 'Tamaño',
      priority: 3,
      align: 'end',
      value: (v) => formatBytes(v.sizeBytes),
    },
    { key: 'actions', label: 'Acciones', render: renderActions },
  ]
}
