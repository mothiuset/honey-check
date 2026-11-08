import type { Inventory, InventorySummary } from '@/application'

export interface InventorySliceState {
  // Inventario que se está viendo: de este equipo o de otro de la carpeta de datos.
  readonly current: Inventory | null
  readonly currentId: string | null
  // Historial del equipo donde corre Honey Check (no del que se está viendo).
  readonly history: readonly InventorySummary[]
  readonly deviceTotal: number
}

export type ExportFeedback =
  { readonly ok: true } | { readonly ok: false; readonly reason: string }
