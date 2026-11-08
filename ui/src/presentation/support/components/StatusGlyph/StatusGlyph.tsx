import type { CheckStatus } from '@/application'
import { CHECK_MARKS } from '../../formatters/supportText'
import styles from './StatusGlyph.module.css'

// Celda de panal con su marca: el mismo hexágono del catálogo, aquí dice cómo terminó algo.
const MARKS: Readonly<Record<CheckStatus, string>> = {
  ok: 'M6.2 10.3l2.6 2.6 5-5.4',
  warn: 'M10 5.6v5.2M10 14.1v.1',
  fail: 'M7 7l6 6M13 7l-6 6',
  info: 'M10 9.2v4.8M10 6.4v.1',
  skipped: 'M6.8 10h6.4',
}

export function StatusGlyph({ status }: { status: CheckStatus }) {
  return (
    <svg
      className={styles.glyph}
      data-status={status}
      viewBox="0 0 20 20"
      role="img"
      aria-label={CHECK_MARKS[status].label}
    >
      <polygon points="10,1 18,5.5 18,14.5 10,19 2,14.5 2,5.5" />
      <path d={MARKS[status]} />
    </svg>
  )
}
