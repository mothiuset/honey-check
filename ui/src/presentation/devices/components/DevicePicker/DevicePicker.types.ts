import type { DeviceVersion } from '@/application'

export interface DevicePickerProps {
  readonly title: string
  readonly value: DeviceVersion | null
  readonly onChange: (value: DeviceVersion | null) => void
}
