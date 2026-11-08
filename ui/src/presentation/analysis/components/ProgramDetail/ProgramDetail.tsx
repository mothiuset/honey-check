import type { SoftwareItem } from '@/application'
import { Value } from '@/presentation/shared/components'
import { programDetail } from '../../formatters/programDetail'
import styles from './ProgramDetail.module.css'

export function ProgramDetail({ item }: { item: SoftwareItem }) {
  return (
    <dl className={styles.grid}>
      {programDetail(item).map((entry) => (
        <div
          key={entry.label}
          className={styles.entry}
          data-wide={entry.wide ?? false}
        >
          <dt className={styles.label}>{entry.label}</dt>
          <dd className={styles.value}>
            <Value display={entry.value} />
          </dd>
        </div>
      ))}
    </dl>
  )
}
