import { useState } from 'react'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'
import { useLinks } from '@/presentation/shared/hooks/useLinks'

/** Logo del programa guardado con el inventario; si no hay o no carga, se usa su inicial. */
export function useProgramIcon(name: string, iconId: string | null) {
  const { inventoryId } = useCurrentInventory()
  const links = useLinks()
  const [failed, setFailed] = useState(false)
  return {
    url:
      !failed && iconId && inventoryId ? links.icon(inventoryId, iconId) : null,
    initial: (name.trim()[0] ?? '?').toUpperCase(),
    onError: () => {
      setFailed(true)
    },
  }
}
