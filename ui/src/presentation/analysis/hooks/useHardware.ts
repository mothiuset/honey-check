import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'

/** Secciones de hardware del inventario que se está viendo. */
export function useHardware() {
  const { inventory, isThisDevice } = useCurrentInventory()
  return {
    inventory,
    isThisDevice,
    device: inventory?.device ?? null,
    hardware: inventory?.hardware ?? null,
    devices: inventory?.devices ?? null,
  }
}
