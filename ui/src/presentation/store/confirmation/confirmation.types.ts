export interface ConfirmationRequest {
  readonly title: string
  readonly message: string
  readonly confirmLabel: string
  readonly danger?: boolean
}

export interface ConfirmationSliceState {
  readonly request: ConfirmationRequest | null
}
