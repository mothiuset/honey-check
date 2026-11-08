import { linkParams, type Check } from '@/application'
import { ActionButton } from '../ActionButton/ActionButton'
import { StatusGlyph } from '../StatusGlyph/StatusGlyph'
import styles from './CheckList.module.css'

const looksLikePath = (text: string) =>
  /^[A-Za-z]:\\|^\\\\|^HK(LM|CU|U|CR)\\/.test(text)

/**
 * Cada elemento con su estado, qué pasó en palabras del técnico y, si hace falta, la siguiente
 * acción. El código de Windows queda plegado en «Detalles técnicos».
 */
export function CheckList({ checks }: { checks: readonly Check[] }) {
  return (
    <ul className={styles.list}>
      {checks.map((check, index) => (
        <li
          key={`${String(index)}-${check.label}`}
          className={styles.item}
          data-status={check.status}
        >
          <StatusGlyph status={check.status} />
          <div className={styles.body}>
            <span
              className={styles.label}
              data-path={looksLikePath(check.label) || undefined}
            >
              {check.label}
            </span>
            {check.detail ? (
              <span className={styles.detail}>{check.detail}</span>
            ) : null}
            {check.technical ? (
              <details className={styles.technical}>
                <summary>Detalles técnicos</summary>
                <code>{check.technical}</code>
              </details>
            ) : null}
          </div>
          {check.fix ? (
            <ActionButton
              size="small"
              tone="primary"
              tool={check.fix.tool}
              params={linkParams(check.fix, null)}
            >
              {check.fix.label}
            </ActionButton>
          ) : null}
        </li>
      ))}
    </ul>
  )
}
