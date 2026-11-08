// Implementación HTTP del puerto sobre la API local de Honey Check.

import type {
  DeviceSearch,
  HoneyCheckGateway,
} from '@/application/ports/HoneyCheckGateway'
import type { Comparison } from '@/domain/comparison/Comparison'
import type { DevicePage, InventorySummary } from '@/domain/devices/Device'
import type { Inventory } from '@/domain/inventory/Inventory'
import type { AppStatus } from '@/domain/session/AppStatus'
import type {
  ParamChoice,
  ParamValue,
  Plan,
  Procedure,
  ProcedureRun,
  Run,
  ToolDefinition,
} from '@/domain/support/Support'
import { query, type ApiClient } from '../../client/ApiClient'

const id = encodeURIComponent

export class HttpHoneyCheckGateway implements HoneyCheckGateway {
  constructor(private readonly client: ApiClient) {}

  async session(): Promise<{ appVersion: string }> {
    const session = await this.client.send<{
      csrfToken: string
      appVersion: string
    }>('/api/session')
    this.client.useCsrfToken(session.csrfToken)
    return { appVersion: session.appVersion }
  }

  status = () => this.client.send<AppStatus>('/api/status')
  startScan = () =>
    this.client.send<undefined>('/api/scans', { method: 'POST' })
  cancelScan = () =>
    this.client.send<undefined>('/api/scans/current/cancel', { method: 'POST' })
  inventories = (deviceKey: string) =>
    this.client.send<InventorySummary[]>(
      `/api/inventories?${query({ device: deviceKey })}`,
    )
  inventory = (inventoryId: string) =>
    this.client.send<Inventory>(`/api/inventories/${id(inventoryId)}`)
  inventorySummary = (inventoryId: string) =>
    this.client.send<InventorySummary>(
      `/api/inventories/${id(inventoryId)}/summary`,
    )
  pendingInventory = () => this.client.send<Inventory>('/api/pending')
  devices = (search: DeviceSearch) =>
    this.client.send<DevicePage>(`/api/devices?${query({ ...search })}`)
  compare = (baseId: string, targetId: string) =>
    this.client.send<Comparison>(
      `/api/comparison?${query({ base: baseId, target: targetId })}`,
    )
  setReference = (inventoryId: string) =>
    this.client.send<undefined>('/api/reference', {
      method: 'POST',
      body: { inventoryId },
    })
  deleteInventory = (inventoryId: string) =>
    this.client.send<undefined>(`/api/inventories/${id(inventoryId)}/delete`, {
      method: 'POST',
    })
  deleteDevice = (deviceKey: string) =>
    this.client.send<{ deleted: number }>(
      `/api/devices/${id(deviceKey)}/delete`,
      { method: 'POST' },
    )
  exportPending = (directory: string) =>
    this.client.send<undefined>('/api/pending/export', {
      method: 'POST',
      body: { directory },
    })
  openFolder = (path?: string) =>
    this.client.send<undefined>('/api/folder/open', {
      method: 'POST',
      body: path ? { path } : {},
    })
  elevate = () =>
    this.client.send<undefined>('/api/elevate', { method: 'POST' })
  exit = () => this.client.send<undefined>('/api/exit', { method: 'POST' })
  downloadUrl = (inventoryId: string) =>
    `/api/inventories/${id(inventoryId)}/download`
  pendingDownloadUrl = () => '/api/pending/download'
  iconUrl = (inventoryId: string, iconId: string) =>
    `/api/inventories/${id(inventoryId)}/icons/${id(iconId)}`

  supportTools = () => this.client.send<ToolDefinition[]>('/api/support/tools')
  supportSource = (name: string) =>
    this.client.send<ParamChoice[]>(
      `/api/support/sources/${encodeURIComponent(name)}`,
    )
  supportPlan = (tool: string, params: Readonly<Record<string, ParamValue>>) =>
    this.client.send<Plan>('/api/support/plans', {
      method: 'POST',
      body: { tool, params },
    })
  supportStart = (planId: string, confirmed: boolean) =>
    this.client.send<Run>('/api/support/runs', {
      method: 'POST',
      body: { planId, confirmed },
    })
  supportRun = (runId: string) =>
    this.client.send<Run>(`/api/support/runs/${id(runId)}`)
  supportCancel = async (runId: string) => {
    await this.client.send<unknown>(`/api/support/runs/${id(runId)}/cancel`, {
      method: 'POST',
    })
  }
  supportHistory = () => this.client.send<Run[]>('/api/support/runs')
  pickPath = async (
    kind: 'folder' | 'file',
    title: string,
    filter: string | null,
  ) =>
    (
      await this.client.send<{ path: string | null }>('/api/pick', {
        method: 'POST',
        body: { kind, title, filter },
      })
    ).path
  supportChanged = async (runId: string) =>
    (
      await this.client.send<{ changed: boolean | null }>(
        `/api/support/runs/${id(runId)}/changed`,
      )
    ).changed
  supportVersions = (tool: string) =>
    this.client.send<Run[]>(
      `/api/support/runs?tool=${encodeURIComponent(tool)}`,
    )
  procedures = () => this.client.send<Procedure[]>('/api/procedures')
  procedureVersions = (slug: string) =>
    this.client.send<Procedure[]>(`/api/procedures/${id(slug)}`)
  saveProcedure = (document: unknown) =>
    this.client.send<Procedure>('/api/procedures', {
      method: 'POST',
      body: document,
    })
  deleteProcedure = (slug: string) =>
    this.client.send<{ removed: number }>(
      `/api/procedures/${id(slug)}/delete`,
      { method: 'POST' },
    )
  procedureRuns = () => this.client.send<ProcedureRun[]>('/api/procedure-runs')
}
