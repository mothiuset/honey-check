import {
  selectDeviceTotal,
  selectReadableHistory,
  selectSession,
  selectViewedSummary,
  selectViewingOtherDevice,
  useAppSelector,
} from '@/presentation/store'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'
import { panelMetrics } from '../formatters/panelMetrics'
import { scanLine } from '../formatters/scanLine'
import { useScanControl } from './useScanControl'

/** Todo lo que el panel muestra: el equipo, el análisis, sus datos clave y dónde se guardó. */
export function usePanel() {
  const { inventory } = useCurrentInventory()
  const control = useScanControl()
  const { status, message } = useAppSelector(selectSession)
  const readable = useAppSelector(selectReadableHistory)
  const deviceTotal = useAppSelector(selectDeviceTotal)
  const viewed = useAppSelector(selectViewedSummary)
  const viewingOther = useAppSelector(selectViewingOtherDevice)

  const device = inventory?.device ?? null
  const last = status?.lastSaved
  const saved =
    last && !control.scanning
      ? { ...last, fullPath: `${last.directory}\\${last.fileName}` }
      : null
  const statuses = Object.fromEntries(
    (control.scanning && control.scan
      ? control.scan.modules
      : (inventory?.modules ?? [])
    ).map((m) => [m.name, m.status]),
  )

  return {
    ...control,
    inventory,
    title:
      device?.hostname.value ??
      (inventory ? 'Equipo sin nombre' : 'Honey Check'),
    subtitle: inventory
      ? [device?.manufacturer.value, device?.model.value]
          .filter(Boolean)
          .join(' ') || 'Fabricante y modelo sin datos'
      : 'Inventario técnico de este equipo, sin instalar nada y sin conexión.',
    statuses,
    scanText: scanLine(control.scan, message),
    versionCount: readable.length,
    deviceTotal,
    showHistoryHint: !control.scanning && readable.length > 0 && !viewingOther,
    showOtherDevicesHint:
      !control.scanning && readable.length === 0 && deviceTotal > 0,
    saved,
    viewed: saved ? null : viewed,
    metrics: inventory ? panelMetrics(inventory) : [],
  }
}
