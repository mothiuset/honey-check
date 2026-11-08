import { RouteLink } from '@/presentation/shared/navigation'
import { useCurrentModule } from '../../hooks/useCurrentModule'
import styles from './RailHeader.module.css'

/** Marca, y en la barra compacta, la sección actual y el botón del menú. */
export function RailHeader({
  menuOpen,
  onToggleMenu,
}: {
  menuOpen: boolean
  onToggleMenu: () => void
}) {
  const { module } = useCurrentModule()
  return (
    <div className={styles.bar} data-part="rail-bar">
      <RouteLink className={styles.brand} href="#panel">
        <img
          src="/icon.svg"
          alt=""
          width="32"
          height="32"
          className={styles.logo}
        />
        <span>Honey Check</span>
      </RouteLink>
      <span className={styles.current}>
        <small className={styles.group}>{module?.group}</small>
        {module?.label}
      </span>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={menuOpen}
        aria-controls="rail-menu"
        onClick={onToggleMenu}
      >
        <span className={styles.icon} aria-hidden="true" />
        Menú
      </button>
    </div>
  )
}
