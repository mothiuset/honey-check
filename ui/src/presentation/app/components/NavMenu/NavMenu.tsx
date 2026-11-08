import { RouteLink } from '@/presentation/shared/navigation'
import { useNavMenu } from '../../hooks/useNavMenu'
import styles from './NavMenu.module.css'

/** Menú por grupos; las secciones con apartados se despliegan y su primera entrada abre la vista. */
export function NavMenu() {
  const menu = useNavMenu()
  return (
    <nav aria-label="Secciones">
      <ul className={styles.groups}>
        {menu.groups.map((group) => (
          <li key={group.label} className={styles.group}>
            <span className={styles.groupLabel}>{group.label}</span>
            <ul className={styles.list}>
              {group.modules.map((module) => (
                <li key={module.id}>
                  {module.sections ? (
                    <>
                      <button
                        type="button"
                        className={styles.parent}
                        data-active={menu.isView(module.id)}
                        aria-expanded={menu.isExpanded(module.id)}
                        aria-controls={`nav-${module.id}`}
                        onClick={() => {
                          menu.toggle(module.id)
                        }}
                      >
                        {module.label}
                      </button>
                      <ul
                        id={`nav-${module.id}`}
                        className={styles.sub}
                        hidden={!menu.isExpanded(module.id)}
                        aria-label={`Apartados de ${module.label}`}
                      >
                        {module.sections.map((section) => (
                          <li key={section.anchor}>
                            <RouteLink
                              href={menu.hrefOf(module.id, section.anchor)}
                              className={styles.subLink}
                              aria-current={
                                menu.isHere(module.id, section.anchor)
                                  ? 'page'
                                  : undefined
                              }
                            >
                              {section.label}
                            </RouteLink>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <RouteLink
                      href={menu.hrefOf(module.id)}
                      className={styles.item}
                      aria-current={menu.isView(module.id) ? 'page' : undefined}
                    >
                      {module.label}
                    </RouteLink>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </nav>
  )
}
