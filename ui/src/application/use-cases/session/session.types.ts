import type { AppStatus } from '@/domain/session/AppStatus'

export type ScanStartResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: 'already_running' | 'failed' }

export type ElevationResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: 'cancelled' | 'failed' }

export type StatusResult =
  | { readonly ok: true; readonly status: AppStatus }
  | { readonly ok: false; readonly reason: 'session_lost' | 'service_stopped' }

export interface SessionUseCases {
  start(): Promise<{ readonly appVersion: string; readonly status: AppStatus }>
  readStatus(): Promise<StatusResult>
  startScan(): Promise<ScanStartResult>
  cancelScan(): Promise<void>
  elevate(): Promise<ElevationResult>
  exit(): Promise<void>
  openFolder(path?: string): Promise<void>
}
