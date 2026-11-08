import { useMemo, useState } from 'react'
import { isDetailComponent, type Peripheral } from '@/application'
import { PERIPHERAL_CATEGORIES } from '@/presentation/shared/formatters'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'

export interface PeripheralGroup {
  readonly category: string
  readonly label: string
  readonly devices: readonly Peripheral[]
}

/**
 * Impresoras, aparatos conectados agrupados por categoría y los que Windows recuerda sin estar
 * conectados (emparejados por Bluetooth y restos). Los inventarios anteriores a 2.2.0 traen las
 * funciones HID sueltas: esas se muestran a pedido.
 */
export function usePeripherals() {
  const { inventory, isThisDevice } = useCurrentInventory()
  const [showComponents, setShowComponents] = useState(false)
  const section = inventory?.peripherals ?? null

  const groups = useMemo(() => {
    const visible = (section?.devices ?? []).filter(
      (device) => showComponents || !isDetailComponent(device),
    )
    const byCategory = new Map<string, Peripheral[]>()
    for (const device of visible) {
      byCategory.set(device.category, [
        ...(byCategory.get(device.category) ?? []),
        device,
      ])
    }
    return [...byCategory.entries()].map(
      ([category, devices]): PeripheralGroup => ({
        category,
        label: PERIPHERAL_CATEGORIES[category] ?? category,
        devices,
      }),
    )
  }, [section, showComponents])

  const disconnected = section?.disconnected ?? []
  return {
    inventory,
    isThisDevice,
    section,
    groups,
    hiddenComponents: (section?.devices ?? []).filter(isDetailComponent).length,
    showComponents,
    setShowComponents,
    paired: disconnected.filter((device) => device.state === 'paired'),
    leftovers: disconnected.filter((device) => device.state === 'leftover'),
    /** Se analizó con una versión anterior: no hay lista de no conectados. */
    oldFormat: section !== null && section.disconnected === undefined,
  }
}
