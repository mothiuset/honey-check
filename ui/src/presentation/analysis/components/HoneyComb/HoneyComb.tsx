import { useHoneyComb } from '../../hooks/useHoneyComb'
import { COMB_HEIGHT, COMB_WIDTH } from '../../formatters/honeyCombCells'
import styles from './HoneyComb.module.css'

/** Panal de módulos: cada celda se llena al terminar su módulo y lleva a su apartado. */
export function HoneyComb({
  statuses,
}: {
  statuses: Readonly<Record<string, string>>
}) {
  const { svg, cells, open } = useHoneyComb(statuses)
  return (
    <svg
      ref={svg}
      className={styles.comb}
      viewBox={`0 0 ${String(COMB_WIDTH)} ${String(COMB_HEIGHT)}`}
      role="group"
      aria-label="Estado de los módulos del análisis"
    >
      <defs>
        <pattern
          id="partial-hatch"
          width="9"
          height="9"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <rect width="9" height="9" className={styles.hatchLight} />
          <rect width="4" height="9" className={styles.hatchDark} />
        </pattern>
      </defs>
      {cells.map((cell) => (
        <g
          key={cell.name}
          className={styles.cell}
          data-cell={cell.name}
          data-status={cell.status}
          tabIndex={0}
          role="link"
          aria-label={`${cell.label}: ${cell.statusText}`}
          onClick={() => {
            open(cell.href)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') open(cell.href)
          }}
        >
          <title>{`${cell.label}: ${cell.statusText}`}</title>
          <polygon points={cell.points} className={styles.shape} />
          <polygon
            points={cell.points}
            className={styles.glow}
            data-part="glow"
          />
          <text x={cell.cx} y={cell.cy - 2} className={styles.label}>
            {cell.label}
          </text>
          {cell.status !== 'ok' && cell.status !== 'pending' ? (
            <text x={cell.cx} y={cell.cy + 13} className={styles.state}>
              {cell.statusText}
            </text>
          ) : null}
        </g>
      ))}
    </svg>
  )
}
