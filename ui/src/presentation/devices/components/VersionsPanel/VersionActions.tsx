import type { DeviceSummary, InventorySummary } from '@/application'
import { Button, LinkButton } from '@/presentation/shared/components'
import type { useVersionActions } from '../../hooks/useVersionActions'
import styles from './VersionsPanel.module.css'

export interface VersionActionsProps {
  readonly device: DeviceSummary
  readonly version: InventorySummary
  readonly actions: ReturnType<typeof useVersionActions>
}

export function VersionActions({
  device,
  version,
  actions,
}: VersionActionsProps) {
  const remove = () => void actions.removeVersion(device, version)
  if (version.invalidReason) {
    return (
      <Button size="small" tone="danger" onClick={remove}>
        Eliminar
      </Button>
    )
  }
  return (
    <span className={styles.actions}>
      <Button size="small" onClick={() => void actions.open(version)}>
        Ver
      </Button>
      <Button
        size="small"
        onClick={() => {
          actions.compare(version)
        }}
      >
        Comparar
      </Button>
      <LinkButton size="small" href={actions.downloadUrl(version.id)} download>
        Descargar
      </LinkButton>
      {version.id === actions.referenceId ? null : (
        <Button
          size="small"
          onClick={() => {
            actions.useAsReference(version)
          }}
        >
          Usar como referencia
        </Button>
      )}
      <Button size="small" tone="danger" onClick={remove}>
        Eliminar
      </Button>
    </span>
  )
}
