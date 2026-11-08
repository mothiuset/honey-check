import type { DeviceSummary, InventorySummary } from '@/application'
import type { ConfirmationRequest } from '@/presentation/shared/types'

const TRASH = 'HoneyCheck-datos\\papelera'

export function versionRemovalQuestion(
  device: DeviceSummary,
  version: InventorySummary,
): ConfirmationRequest {
  return {
    title: 'Eliminar esta versión',
    message: `Se moverá la versión ${String(version.sequence ?? '?')} de ${device.hostname ?? 'este equipo'} a la papelera de Honey Check (${TRASH}). Puede recuperarse desde esa carpeta.`,
    confirmLabel: 'Eliminar versión',
    danger: true,
  }
}

export function deviceRemovalQuestion(
  device: DeviceSummary,
): ConfirmationRequest {
  return {
    title: 'Eliminar el equipo',
    message: `Se moverán las ${String(device.inventoryCount)} versiones de ${device.hostname ?? 'este equipo'} a la papelera de Honey Check. Puede recuperarlas desde ${TRASH}.`,
    confirmLabel: 'Eliminar equipo',
    danger: true,
  }
}
