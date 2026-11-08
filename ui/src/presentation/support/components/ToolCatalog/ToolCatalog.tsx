import { RouteLink } from '@/presentation/shared/navigation'
import { toolHref } from '../../formatters/supportRoutes'
import { RISKS } from '../../formatters/supportText'
import type { ToolGroup } from '../../hooks/useSupportCatalog'
import styles from './ToolCatalog.module.css'

export const categoryAnchor = (category: string) =>
  category
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')

/**
 * Herramientas por categoría, como filas de un panal: la celda dice el riesgo con su color y el
 * texto de debajo lo dice con palabras.
 */
export function ToolCatalog({ groups }: { groups: readonly ToolGroup[] }) {
  return (
    <>
      {groups.map((group) => (
        <section key={group.category} className={styles.group}>
          <h2 id={categoryAnchor(group.category)} tabIndex={-1}>
            {group.category}
          </h2>
          <ul className={styles.list}>
            {group.tools.map((tool) => (
              <li key={tool.id}>
                <RouteLink
                  className={styles.tool}
                  href={toolHref(tool.id)}
                  data-tool={tool.id}
                  data-risk={tool.risk}
                >
                  <span className={styles.cell} aria-hidden="true" />
                  <span className={styles.title}>{tool.title}</span>
                  <span className={styles.description}>{tool.description}</span>
                  <span className={styles.meta}>
                    <span className={styles.risk}>
                      {RISKS[tool.risk].label}
                    </span>
                    {tool.requiresAdmin ? ', requiere administrador' : ''}
                  </span>
                </RouteLink>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  )
}
