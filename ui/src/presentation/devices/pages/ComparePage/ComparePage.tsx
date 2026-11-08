import { Button, Lede, Notice } from '@/presentation/shared/components'
import { ComparisonArea } from '../../components/ComparisonArea/ComparisonArea'
import { ComparisonFilter } from '../../components/ComparisonFilter/ComparisonFilter'
import { DevicePicker } from '../../components/DevicePicker/DevicePicker'
import { SoftwareComparison } from '../../components/SoftwareComparison/SoftwareComparison'
import { areaLabel, emptyFilterText } from '../../formatters/comparisonValue'
import { useComparison } from '../../hooks/useComparison'
import styles from './ComparePage.module.css'

export function ComparePage() {
  const comparison = useComparison()
  const { result } = comparison
  return (
    <>
      <h1>Comparar</h1>
      <Lede>
        Elija dos versiones: del mismo equipo para ver qué cambió, o de otro
        equipo que funcione bien (la referencia) para detectar qué está
        distinto.
      </Lede>
      <div className={styles.pickers}>
        <DevicePicker
          title="Base"
          value={comparison.base}
          onChange={comparison.pickBase}
        />
        <DevicePicker
          title="Comparar con"
          value={comparison.target}
          onChange={comparison.pickTarget}
        />
      </div>
      <div className={styles.actions}>
        <Button
          tone="primary"
          disabled={!comparison.ready || comparison.loading}
          onClick={comparison.run}
        >
          Comparar
        </Button>
        {comparison.ready ? null : (
          <Lede>Elija un equipo y una versión en cada lado.</Lede>
        )}
      </div>

      {result ? (
        <>
          <h2 id="comparacion" tabIndex={-1}>
            Resultado de la comparación
          </h2>
          {result.sameDevice === false ? (
            <Notice tone="bad">
              <p>
                Son equipos distintos: las diferencias de identidad son
                esperables.
              </p>
            </Notice>
          ) : null}
          <ComparisonFilter
            value={comparison.filter}
            differences={comparison.totals.differences}
            same={comparison.totals.same}
            onChange={comparison.setFilter}
          />
          {comparison.areas.length ? null : (
            <Lede>{emptyFilterText(comparison.filter)}</Lede>
          )}
          {comparison.areas.map((area) => (
            <ComparisonArea key={area.area} area={area} />
          ))}
          <SoftwareComparison
            rows={comparison.software}
            all={result.software}
          />
          {result.notComparable.length ? (
            <Notice>
              <p>
                No comparable porque falló en alguna de las dos versiones:{' '}
                {result.notComparable.map(areaLabel).join(', ')}.
              </p>
            </Notice>
          ) : null}
        </>
      ) : null}
    </>
  )
}
