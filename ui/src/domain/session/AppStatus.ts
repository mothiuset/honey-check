// Estado del servicio local: el equipo donde corre, la carpeta de datos y el análisis en curso.

import type { ModuleStatus } from '../inventory/Inventory'

export type ScanState =
  'idle' | 'running' | 'cancelling' | 'finished' | 'cancelled' | 'failed'

export interface ScanProgress {
  readonly state: ScanState
  readonly scanId: string | null
  readonly startedAt: string | null
  readonly finishedAt: string | null
  readonly completed: number
  readonly total: number
  readonly detail: string | null
  readonly modules: readonly {
    readonly name: string
    readonly status: ModuleStatus
    readonly durationMs: number | null
    readonly issueCount: number
  }[]
}

export function isScanActive(scan: ScanProgress | undefined): boolean {
  return scan?.state === 'running' || scan?.state === 'cancelling'
}

export interface Workspace {
  readonly directory: string
  readonly available: boolean
  readonly writable: boolean
}

export interface SavedVersion {
  readonly id: string
  readonly deviceKey: string
  readonly sequence: number
  readonly fileName: string
  readonly directory: string
}

export interface AppStatus {
  readonly service: string
  readonly appVersion: string
  readonly isElevated: boolean | null
  readonly currentDevice: {
    readonly deviceKey: string
    readonly identityBasis: string
    readonly hostname: string | null
  } | null
  readonly workspace: Workspace
  readonly scan: ScanProgress
  readonly referenceId: string | null
  readonly exportFailure: {
    readonly reason: string
    readonly inventoryId: string
  } | null
  readonly lastSaved: SavedVersion | null
}
