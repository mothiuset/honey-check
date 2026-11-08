import type { Fact } from '@/application'
import { Copyable } from '@/presentation/shared/components'
import styles from './Readout.module.css'

// Una ruta va en su propia línea y en monoespaciada; una frase larga, en su línea y en texto.
const isPath = (value: string) => /^[A-Za-z]:\\|^\\\\/.test(value)
const isLong = (value: string) => !isPath(value) && value.length > 28

/** Los datos de un resultado como la placa de lectura de un instrumento: etiqueta y cifra. */
export function Readout({ facts }: { facts: readonly Fact[] }) {
  return (
    <dl className={styles.readout}>
      {facts.map((fact) => {
        const value = fact.value ?? 'Sin dato'
        return (
          <div
            key={fact.label}
            className={styles.item}
            data-tone={fact.tone}
            data-path={isPath(value) || undefined}
            data-long={isLong(value) || undefined}
          >
            <dt>{fact.label}</dt>
            <dd>
              <Copyable text={value} />
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
