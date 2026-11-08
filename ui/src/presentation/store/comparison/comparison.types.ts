import type { Comparison, DeviceVersion } from '@/application'

export type ComparisonFilter = 'differences' | 'same' | 'all'

export interface ComparisonSliceState {
  readonly base: DeviceVersion | null
  readonly target: DeviceVersion | null
  readonly result: Comparison | null
  readonly loading: boolean
  readonly filter: ComparisonFilter
}
