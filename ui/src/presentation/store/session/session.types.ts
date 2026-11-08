import type { AppStatus } from '@/application'

export interface SessionSliceState {
  readonly ready: boolean
  // Mensaje final cuando la sesión terminó (cierre, pérdida de sesión o relanzamiento elevado).
  readonly stopped: string | null
  readonly appVersion: string
  readonly status: AppStatus | null
  // Aviso de la última acción (análisis, elevación); se muestra en la barra de estado.
  readonly message: string | null
}
