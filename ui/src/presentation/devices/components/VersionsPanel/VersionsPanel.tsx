import type { DeviceSummary } from '@/application'
import { Button, DataTable, Lede } from '@/presentation/shared/components'
import { versionColumns } from '../../formatters/deviceColumns'
import { useDeviceVersions } from '../../hooks/useDeviceVersions'
import { useVersionActions } from '../../hooks/useVersionActions'
import { VersionActions } from './VersionActions'
import styles from './VersionsPanel.module.css'

/** Contenido desplegado de un equipo: sus versiones y lo que se puede hacer con cada una. */
export function VersionsPanel({ device }: { device: DeviceSummary }) {
  const versions = useDeviceVersions(device)
  const actions = useVersionActions()
  const columns = versionColumns({
    referenceId: actions.referenceId,
    renderActions: (version) => (
      <VersionActions device={device} version={version} actions={actions} />
    ),
  })

  return (
    <div data-part="versions">
      <div className={styles.toolbar}>
        <Button
          size="small"
          onClick={() => {
            actions.reload(device)
          }}
        >
          Actualizar lista
        </Button>
        <Button
          size="small"
          tone="danger"
          onClick={() => void actions.removeDevice(device)}
        >
          Eliminar equipo
        </Button>
      </div>
      {versions ? (
        <DataTable
          columns={columns}
          rows={versions}
          rowKey={(version) => version.id}
          emptyText="Sin versiones."
        />
      ) : (
        <Lede live>Cargando versiones.</Lede>
      )}
    </div>
  )
}
