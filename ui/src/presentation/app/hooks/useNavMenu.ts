import { useEffect, useState } from 'react'
import { hrefOf, useRoute } from '@/presentation/shared/navigation'
import { GROUPS, MODULES } from '../routing/modules'

const groups = GROUPS.map((label) => ({
  label,
  modules: MODULES.filter((module) => module.group === label),
}))

/** Menú por grupos: las secciones con apartados se despliegan sin navegar (acordeón). */
export function useNavMenu() {
  const route = useRoute()
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set([route.view]),
  )

  useEffect(() => {
    setExpanded((current) =>
      current.has(route.view) ? current : new Set([...current, route.view]),
    )
  }, [route.view])

  function toggle(id: string): void {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return {
    groups,
    toggle,
    isExpanded: (id: string) => expanded.has(id),
    isView: (id: string) => route.view === id,
    isHere: (id: string, anchor: string) =>
      route.view === id && route.section === anchor,
    hrefOf,
  }
}
