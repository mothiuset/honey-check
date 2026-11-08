import type { DisplayValue } from '../../types/display.types'
import { Copyable } from '../Copyable'
import { Tag } from '../Tag'
import styles from './Value.module.css'

/** Un dato: limpio si se conoce, con sus insignias; «Sin dato» y el motivo si no. */
export function Value({ display }: { display: DisplayValue }) {
  if (display.text === null) {
    return (
      <span className={styles.unknown}>
        Sin dato
        {display.reason ? (
          <small className={styles.reason}>{display.reason}</small>
        ) : null}
      </span>
    )
  }
  return (
    <span title={display.source ? `Origen: ${display.source}` : undefined}>
      <Copyable text={display.text} mono={display.mono}>
        {display.text}
      </Copyable>
      {display.tags.map((tag) => (
        <Tag key={tag.label} tone={tag.tone ?? 'neutral'} title={tag.hint}>
          {tag.label}
        </Tag>
      ))}
    </span>
  )
}
