import { areaLabel, fieldLabel } from '../../formatters/comparisonValue'
import type { ComparisonArea as Area } from '../../types/devices.types'
import styles from './ComparisonArea.module.css'
import { SideBySideTable } from './SideBySideTable'

/** Un área (equipo, memoria, sistema…) con su conteo de diferencias y sus filas filtradas. */
export function ComparisonArea({ area }: { area: Area }) {
  return (
    <section className={styles.area}>
      <header className={styles.header}>
        <h3 className={styles.title}>{areaLabel(area.area)}</h3>
        <span
          className={styles.count}
          data-tone={area.differences ? 'diff' : 'ok'}
        >
          {area.differences
            ? `${String(area.differences)} ${area.differences === 1 ? 'diferencia' : 'diferencias'}`
            : 'Sin diferencias'}
        </span>
      </header>
      <SideBySideTable rows={area.rows} label={fieldLabel} />
    </section>
  )
}
