import { useProgramIcon } from '../../hooks/useProgramIcon'
import styles from './AppIcon.module.css'

export function AppIcon({
  name,
  iconId,
}: {
  name: string
  iconId: string | null
}) {
  const icon = useProgramIcon(name, iconId)
  return icon.url ? (
    <img
      className={styles.icon}
      src={icon.url}
      alt=""
      width="22"
      height="22"
      loading="lazy"
      onError={icon.onError}
    />
  ) : (
    <span className={styles.monogram} aria-hidden="true">
      {icon.initial}
    </span>
  )
}
