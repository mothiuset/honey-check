import { Button, Lede } from '@/presentation/shared/components'
import { RouteLink } from '@/presentation/shared/navigation'
import { HoneyComb } from '../../components/HoneyComb/HoneyComb'
import { IssueList } from '../../components/IssueList/IssueList'
import { MetricCard } from '../../components/MetricCard/MetricCard'
import { SavedLocation } from '../../components/SavedLocation/SavedLocation'
import { usePanel } from '../../hooks/usePanel'
import styles from './PanelPage.module.css'

export function PanelPage() {
  const panel = usePanel()
  return (
    <>
      <div className={styles.top}>
        <div>
          <h1 className={styles.name} data-part="plate-name">
            {panel.title}
          </h1>
          <p className={styles.sub} data-part="plate-sub">
            {panel.subtitle}
          </p>
          {panel.scanning ? (
            <Button disabled={panel.cancelling} onClick={panel.cancel}>
              Cancelar análisis
            </Button>
          ) : (
            <Button tone="primary" onClick={panel.start}>
              {panel.versionCount ? 'Actualizar análisis' : 'Analizar equipo'}
            </Button>
          )}
          <p className={styles.scanLine} role="status">
            {panel.scanText}
          </p>
          {panel.showHistoryHint ? (
            <Lede>
              Este equipo tiene {panel.versionCount} análisis guardados. Uno
              nuevo se guarda como otra versión y no reemplaza a los anteriores.
            </Lede>
          ) : null}
          {panel.showOtherDevicesHint ? (
            <Lede>
              Este equipo todavía no tiene análisis. En esta carpeta hay
              inventarios de {panel.deviceTotal}{' '}
              {panel.deviceTotal === 1 ? 'equipo' : 'equipos'}:{' '}
              <RouteLink href="#equipos">ver equipos</RouteLink>.
            </Lede>
          ) : null}
        </div>
        <HoneyComb statuses={panel.statuses} />
      </div>

      {panel.saved ? (
        <SavedLocation
          prefix={`Guardado como versión ${String(panel.saved.sequence)} de este equipo en`}
          directory={panel.saved.directory}
          fileName={panel.saved.fileName}
        />
      ) : null}
      {panel.viewed ? (
        <SavedLocation
          prefix="Archivo de este análisis:"
          directory={panel.viewed.directory}
          fileName={panel.viewed.fileName}
        />
      ) : null}

      {panel.inventory ? (
        <>
          <h2 id="resumen" tabIndex={-1}>
            Resumen
          </h2>
          <div className={styles.metrics}>
            {panel.metrics.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>
          {panel.inventory.errors.length ? (
            <>
              <h2 id="problemas" tabIndex={-1}>
                Qué no se pudo leer
              </h2>
              <IssueList issues={panel.inventory.errors} />
            </>
          ) : null}
          {panel.inventory.warnings.length ? (
            <details className={styles.warnings}>
              <summary>
                Advertencias del análisis ({panel.inventory.warnings.length})
              </summary>
              <IssueList issues={panel.inventory.warnings} />
            </details>
          ) : null}
        </>
      ) : null}
    </>
  )
}
