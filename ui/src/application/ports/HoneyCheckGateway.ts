// Lo que la interfaz necesita del servicio local de Honey Check. El adaptador HTTP lo implementa.

import type { Comparison } from '@/domain/comparison/Comparison'
import type { DevicePage, InventorySummary } from '@/domain/devices/Device'
import type { Inventory } from '@/domain/inventory/Inventory'
import type { AppStatus } from '@/domain/session/AppStatus'
import type {
  ParamValue,
  Plan,
  Procedure,
  ProcedureRun,
  Run,
  ToolDefinition,
  ParamChoice,
} from '@/domain/support/Support'

export interface DeviceSearch {
  readonly q?: string
  readonly manufacturer?: string
  readonly type?: string
  readonly os?: string
  readonly status?: string
  readonly sort?: string
  readonly order?: 'asc' | 'desc'
  readonly page?: number
  readonly size?: number
}

/** Fallo conocido del servicio: código estable (`scan_already_running`…) y motivo opcional. */
export class GatewayError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    readonly reason: string | null,
  ) {
    super(reason ?? code ?? `HTTP ${String(status)}`)
    this.name = 'GatewayError'
  }
}

export interface HoneyCheckGateway {
  session(): Promise<{ readonly appVersion: string }>
  status(): Promise<AppStatus>
  startScan(): Promise<void>
  cancelScan(): Promise<void>
  inventories(deviceKey: string): Promise<readonly InventorySummary[]>
  inventory(id: string): Promise<Inventory>
  inventorySummary(id: string): Promise<InventorySummary>
  pendingInventory(): Promise<Inventory>
  devices(search: DeviceSearch): Promise<DevicePage>
  compare(baseId: string, targetId: string): Promise<Comparison>
  setReference(id: string): Promise<void>
  deleteInventory(id: string): Promise<void>
  deleteDevice(deviceKey: string): Promise<{ readonly deleted: number }>
  exportPending(directory: string): Promise<void>
  openFolder(path?: string): Promise<void>
  elevate(): Promise<void>
  exit(): Promise<void>
  downloadUrl(id: string): string
  pendingDownloadUrl(): string
  iconUrl(inventoryId: string, iconId: string): string
  supportTools(): Promise<readonly ToolDefinition[]>
  supportSource(name: string): Promise<readonly ParamChoice[]>
  supportPlan(
    tool: string,
    params: Readonly<Record<string, ParamValue>>,
  ): Promise<Plan>
  supportStart(planId: string, confirmed: boolean): Promise<Run>
  supportRun(runId: string): Promise<Run>
  supportCancel(runId: string): Promise<void>
  supportHistory(): Promise<readonly Run[]>
  /** Versiones livianas de una herramienta (resumen, sin tablas ni gráficos). */
  supportVersions(tool: string): Promise<readonly Run[]>
  /** Si el equipo cambió desde el resultado de una consulta (null: no se sabe). */
  supportChanged(runId: string): Promise<boolean | null>
  /** Diálogo de Windows para elegir una carpeta o un archivo; null si se canceló. */
  pickPath(
    kind: 'folder' | 'file',
    title: string,
    filter: string | null,
  ): Promise<string | null>
  procedures(): Promise<readonly Procedure[]>
  procedureVersions(slug: string): Promise<readonly Procedure[]>
  saveProcedure(document: unknown): Promise<Procedure>
  deleteProcedure(slug: string): Promise<{ readonly removed: number }>
  procedureRuns(): Promise<readonly ProcedureRun[]>
}
