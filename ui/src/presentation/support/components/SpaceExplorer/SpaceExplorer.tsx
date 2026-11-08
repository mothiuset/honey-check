import { useRef, useState } from 'react'
import {
  linkParams,
  type ChartNode,
  type ResultChart,
  type ResultRow,
} from '@/application'
import { formatBytes } from '@/presentation/shared/formatters'
import { ActionButton } from '../ActionButton/ActionButton'
import shareStyles from '../ShareBars/ShareBars.module.css'
import { ShareRow } from '../ShareBars/ShareRow'
import styles from './SpaceExplorer.module.css'

// Los datos del elemento llenan los `{campo}` de sus acciones (ruta, programa…).
const asRow = (node: ChartNode): ResultRow => ({
  name: node.name,
  value: node.value,
  path: node.path ?? null,
  id: node.id ?? null,
})

function NodeActions({ node }: { node: ChartNode }) {
  return (
    <>
      {(node.actions ?? []).map((action) => (
        <ActionButton
          key={`${action.tool}-${action.label}`}
          size="small"
          tone={action.tone === 'bad' ? 'danger' : 'default'}
          tool={action.tool}
          params={linkParams(action, asRow(node))}
        >
          {action.label}
        </ActionButton>
      ))}
    </>
  )
}

/**
 * El espacio nivel por nivel: cada fila es una parte del total. Si tiene más niveles, un clic
 * entra y las migas vuelven; si no, un clic la elige y muestra debajo lo que se puede hacer con
 * ella (abrir su carpeta, analizarla aparte, desinstalar un programa…).
 */
export function SpaceExplorer({ chart }: { chart: ResultChart }) {
  const root = chart.data[0]
  const [trail, setTrail] = useState<readonly ChartNode[]>(root ? [root] : [])
  const [picked, setPicked] = useState<ChartNode | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const current = trail[trail.length - 1]
  if (!root || !current) return null

  const go = (next: readonly ChartNode[]) => {
    setTrail(next)
    setPicked(null)
    // El foco acompaña al técnico: al entrar o volver, queda en el nombre de la carpeta.
    requestAnimationFrame(() => heading.current?.focus())
  }
  const children = current.children ?? []
  const largest = Math.max(0, ...children.map((child) => child.value))

  return (
    <section className={styles.explorer} aria-label={chart.title}>
      <nav aria-label="Ruta dentro del análisis" hidden={trail.length < 2}>
        <ol className={styles.crumbs}>
          {trail.map((node, index) => (
            <li key={`${String(index)}-${node.name}`}>
              {index < trail.length - 1 ? (
                <button
                  type="button"
                  onClick={() => {
                    go(trail.slice(0, index + 1))
                  }}
                >
                  {node.name}
                </button>
              ) : (
                <span aria-current="location">{node.name}</span>
              )}
            </li>
          ))}
        </ol>
      </nav>
      <div className={styles.head}>
        <h3 ref={heading} tabIndex={-1} className={styles.heading}>
          {current.name}
        </h3>
        <NodeActions node={current} />
        <span className={styles.total}>{formatBytes(current.value)}</span>
      </div>
      {children.length ? (
        <ul className={shareStyles.list}>
          {children.map((child) => {
            const deeper = Boolean(child.children?.length)
            const choosable = !deeper && Boolean(child.actions?.length)
            return (
              <ShareRow
                key={`${child.name}-${child.path ?? ''}-${child.id ?? ''}`}
                name={child.name}
                detail={child.detail}
                value={child.value}
                total={current.value}
                scale={largest}
                format={formatBytes}
                onOpen={
                  deeper
                    ? () => {
                        go([...trail, child])
                      }
                    : undefined
                }
                expanded={picked === child}
                onToggle={
                  choosable
                    ? () => {
                        setPicked(picked === child ? null : child)
                      }
                    : undefined
                }
                actions={<NodeActions node={child} />}
              />
            )
          })}
        </ul>
      ) : (
        <p className={styles.empty}>El análisis no desglosó esta carpeta.</p>
      )}
    </section>
  )
}
