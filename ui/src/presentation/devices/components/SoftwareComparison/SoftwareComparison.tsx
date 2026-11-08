import type { ComparisonRow } from '@/application'
import { Lede } from '@/presentation/shared/components'
import { useSoftwareComparison } from '../../hooks/useSoftwareComparison'
import areaStyles from '../ComparisonArea/ComparisonArea.module.css'
import { SideBySideTable } from '../ComparisonArea/SideBySideTable'
import styles from './SoftwareComparison.module.css'

export interface SoftwareComparisonProps {
  readonly rows: readonly ComparisonRow[]
  readonly all: readonly ComparisonRow[]
}

const programName = (row: ComparisonRow) => row.field

/** Programas nuevos, retirados, actualizados e iguales, con buscador. */
export function SoftwareComparison({ rows, all }: SoftwareComparisonProps) {
  const software = useSoftwareComparison(rows, all)
  return (
    <section className={areaStyles.area}>
      <header className={areaStyles.header}>
        <h3 className={areaStyles.title}>Software</h3>
        <span
          className={areaStyles.count}
          data-tone={software.hasDifferences ? 'diff' : 'ok'}
        >
          {software.summary}
        </span>
      </header>
      {rows.length ? null : <Lede>Ningún programa con este filtro.</Lede>}
      <input
        hidden={!rows.length}
        type="search"
        className={styles.search}
        value={software.search}
        placeholder="Buscar programa"
        aria-label="Buscar programa en la comparación"
        onChange={(event) => {
          software.setSearch(event.target.value)
        }}
      />
      {software.groups.map((group) => (
        <div key={group.key}>
          <h4>
            {group.label} ({group.rows.length})
          </h4>
          <SideBySideTable
            rows={group.rows}
            label={programName}
            showHeader={false}
            showState={false}
          />
        </div>
      ))}
    </section>
  )
}
