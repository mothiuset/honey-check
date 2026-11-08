import type { ParamValue, Plan, Run } from '@/application'
import type { SupportNotice } from '../support/support.types'

/** Lo que se pide ejecutar desde una fila, un elemento o un enlace: herramienta y datos. */
export interface ActionRequest {
  readonly tool: string
  readonly label: string
  readonly params: Readonly<Record<string, ParamValue>>
}

/** Una acción que corre sin pantalla propia: un aviso breve dice cómo va y cómo terminó. */
export interface ActionToast {
  readonly id: number
  readonly label: string
  readonly run: Run | null
  readonly notice: SupportNotice | null
}

/** Un cambio revisado y ejecutado en un panel sobre la pantalla actual. */
export interface ActionPanel {
  readonly tool: string
  readonly title: string
  readonly preparing: boolean
  readonly plan: Plan | null
  readonly run: Run | null
  readonly notice: SupportNotice | null
}

export interface ActionsSliceState {
  readonly toasts: readonly ActionToast[]
  readonly panel: ActionPanel | null
}
