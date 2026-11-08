import type { ReactNode } from 'react'
import type { PhysicalDisk } from '@/application'
import { DataTable, Tag, Value } from '@/presentation/shared/components'
import {
  describe,
  describeQuiet,
  formatBytes,
} from '@/presentation/shared/formatters'
import { partitionColumns } from '../../formatters/storageColumns'
import {
  diskChips,
  systemPartitions,
  volumeUsages,
} from '../../formatters/storageUsage'
import { UsageBar } from '../UsageBar/UsageBar'
import styles from './DiskCard.module.css'

interface DiskCardProps {
  readonly disk: PhysicalDisk
  readonly anchor: string
  /** Acciones de una unidad por su letra (abrir, analizar): solo en el análisis de este equipo. */
  readonly actions?: ((letter: string) => ReactNode) | null
}

/**
 * Un disco: modelo, marca (o la de su controladora), tipo y salud; cada unidad con su letra, su
 * uso y sus acciones. Las particiones que Windows reserva quedan plegadas.
 */
export function DiskCard({ disk, anchor, actions = null }: DiskCardProps) {
  const reserved = systemPartitions(disk)
  const maker = disk.manufacturer.value
    ? describe(disk.manufacturer)
    : disk.controllerVendor
      ? null
      : describe(disk.manufacturer)
  return (
    <article className={styles.disk}>
      <header className={styles.header}>
        <h2 id={anchor} tabIndex={-1} className={styles.title}>
          {disk.model.value ?? 'Unidad sin modelo'}
        </h2>
        {diskChips(disk).map((chip) => (
          <Tag key={chip.label} tone={chip.tone}>
            {chip.label}
          </Tag>
        ))}
      </header>
      <dl className={styles.facts}>
        <div>
          <dt>Capacidad</dt>
          <dd>
            <Value display={describeQuiet(disk.capacityBytes, formatBytes)} />
          </dd>
        </div>
        <div>
          <dt>{maker ? 'Fabricante' : 'Controladora'}</dt>
          <dd>{maker ? <Value display={maker} /> : disk.controllerVendor}</dd>
        </div>
        <div>
          <dt>Número de serie</dt>
          <dd>
            <Value display={describe(disk.serialNumber)} />
          </dd>
        </div>
      </dl>
      <ul className={styles.volumes}>
        {volumeUsages(disk).map((usage) => (
          <li key={usage.drive + usage.name}>
            <UsageBar usage={usage} />
            {actions && usage.letter ? (
              <span className={styles.actions}>{actions(usage.letter)}</span>
            ) : null}
          </li>
        ))}
      </ul>
      {reserved.length ? (
        <details className={styles.reserved}>
          <summary>
            {reserved.length} partici{reserved.length === 1 ? 'ón' : 'ones'} que
            Windows reserva (sin letra)
          </summary>
          <DataTable
            columns={partitionColumns}
            rows={reserved}
            rowKey={(partition) => String(partition.number)}
          />
        </details>
      ) : null}
    </article>
  )
}
