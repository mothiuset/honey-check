import type { SoftwareItem } from '@/application'
import { AppIcon } from '../AppIcon/AppIcon'
import styles from './ProgramName.module.css'

export function ProgramName({ item }: { item: SoftwareItem }) {
  return (
    <span className={styles.program}>
      <AppIcon name={item.name} iconId={item.iconId} />
      <span>{item.name}</span>
    </span>
  )
}
