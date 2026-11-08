import type { Issue } from '@/application'
import { MODULE_LABELS } from '@/presentation/shared/formatters'
import styles from './IssueList.module.css'

/** Problemas del análisis, con el módulo que los produjo y su origen al pasar el puntero. */
export function IssueList({ issues }: { issues: readonly Issue[] }) {
  return (
    <ul className={styles.list}>
      {issues.map((issue) => (
        <li
          key={issue.module + issue.code + issue.message}
          className={styles.item}
          title={issue.source ?? undefined}
        >
          <strong>{MODULE_LABELS[issue.module] ?? issue.module}</strong>:{' '}
          {issue.message}
        </li>
      ))}
    </ul>
  )
}
