import {
  selectCurrentInventory,
  selectCurrentInventoryId,
  selectViewingOtherDevice,
  useAppSelector,
} from '@/presentation/store'

/**
 * El inventario que se está viendo, su identificador (null si es un análisis sin guardar) y si es
 * de este equipo: solo entonces se ofrecen las herramientas de soporte sobre lo que muestra.
 */
export function useCurrentInventory() {
  return {
    inventory: useAppSelector(selectCurrentInventory),
    inventoryId: useAppSelector(selectCurrentInventoryId),
    isThisDevice: !useAppSelector(selectViewingOtherDevice),
  }
}
