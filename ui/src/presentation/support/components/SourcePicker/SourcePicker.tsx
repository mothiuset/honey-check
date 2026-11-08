import type { ParamChoice, ToolParam } from '@/application'
import { Button } from '@/presentation/shared/components'
import { useSourceChoices } from '../../hooks/useSourceChoices'
import styles from './SourcePicker.module.css'

interface SourcePickerProps {
  readonly param: ToolParam & { readonly source: string }
  readonly value: readonly string[]
  readonly onChange: (value: readonly string[]) => void
  /** Varias (casillas) o una sola (botones de radio). */
  readonly multiple?: boolean
}

function groupsOf(choices: readonly ParamChoice[]) {
  const groups = new Map<string, ParamChoice[]>()
  for (const choice of choices) {
    const key = choice.group ?? ''
    groups.set(key, [...(groups.get(key) ?? []), choice])
  }
  return [...groups.entries()]
}

/**
 * Opciones que se leen del equipo, agrupadas (cada disco físico con sus particiones): casilla,
 * nombre, detalle y una barra de uso. Lo que no se puede elegir se muestra con el motivo.
 */
export function SourcePicker({
  param,
  value,
  onChange,
  multiple = true,
}: SourcePickerProps) {
  const { choices, failed, reload } = useSourceChoices(param.source)
  const chosen = new Set(value)
  const toggle = (choice: string, on: boolean) => {
    if (!multiple) {
      onChange([choice])
      return
    }
    onChange(on ? [...value, choice] : value.filter((item) => item !== choice))
  }
  return (
    <fieldset className={styles.picker}>
      <legend className={styles.legend}>
        {param.label}
        <Button size="small" tone="ghost" onClick={reload}>
          Volver a leer
        </Button>
      </legend>
      {param.help ? <p className={styles.help}>{param.help}</p> : null}
      {failed ? (
        <p className={styles.help}>
          No se pudieron leer. Use «Volver a leer» o escriba una carpeta.
        </p>
      ) : null}
      {choices === null && !failed ? (
        <p className={styles.help}>Leyendo…</p>
      ) : null}
      {groupsOf(choices ?? []).map(([group, items]) => (
        <section
          key={group}
          className={styles.group}
          aria-label={group || param.label}
        >
          {group ? <h3 className={styles.title}>{group}</h3> : null}
          <ul className={styles.list}>
            {items.map((choice) => {
              const full = (choice.used ?? 0) >= 0.9
              const disabled = Boolean(choice.disabledReason)
              return (
                <li
                  key={choice.value}
                  className={styles.item}
                  data-disabled={disabled || undefined}
                >
                  <label className={styles.row}>
                    {disabled ? (
                      <span className={styles.box} aria-hidden="true" />
                    ) : (
                      <input
                        type={multiple ? 'checkbox' : 'radio'}
                        name={param.name}
                        checked={chosen.has(choice.value)}
                        onChange={(event) => {
                          toggle(choice.value, event.target.checked)
                        }}
                      />
                    )}
                    <span className={styles.name}>{choice.label}</span>
                    <span className={styles.detail}>
                      {choice.disabledReason ?? choice.detail}
                    </span>
                    {choice.used !== null && choice.used !== undefined ? (
                      <svg
                        className={styles.bar}
                        data-full={full || undefined}
                        viewBox="0 0 100 4"
                        preserveAspectRatio="none"
                        aria-label={`${String(Math.round(choice.used * 100))} % usado`}
                        role="img"
                      >
                        <rect className={styles.track} width="100" height="4" />
                        <rect
                          className={styles.fill}
                          width={(choice.used * 100).toFixed(1)}
                          height="4"
                        />
                      </svg>
                    ) : (
                      <span />
                    )}
                  </label>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </fieldset>
  )
}
