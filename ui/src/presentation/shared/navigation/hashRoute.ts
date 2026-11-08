// Rutas `#vista/apartado?parámetros`: sin servidor de rutas y sin dependencia externa.
// Volver a pulsar el enlace actual no cambia el hash; se cuenta como una «revelación» para volver
// a desplazar y enfocar el apartado.

export interface Route {
  readonly view: string
  readonly section: string
  readonly params: URLSearchParams
  // Cambia con cada navegación, también al repetir el mismo enlace.
  readonly visit: number
}

let visit = 0
let cached: { hash: string; visit: number; route: Route } | null = null
const listeners = new Set<() => void>()

function notify(): void {
  visit += 1
  for (const listener of listeners) listener()
}

export function parseRoute(hash: string, count = 0): Route {
  const [path = '', search = ''] = hash.replace(/^#\/?/, '').split('?')
  const [view = '', section = ''] = path.split('/')
  return {
    view: view || 'panel',
    section,
    params: new URLSearchParams(search),
    visit: count,
  }
}

export function currentRoute(): Route {
  const hash = window.location.hash
  if (cached?.hash !== hash || cached.visit !== visit)
    cached = { hash, visit, route: parseRoute(hash, visit) }
  return cached.route
}

export function subscribeRoute(listener: () => void): () => void {
  listeners.add(listener)
  if (listeners.size === 1) window.addEventListener('hashchange', notify)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) window.removeEventListener('hashchange', notify)
  }
}

export function hrefOf(
  view: string,
  section = '',
  params?: Readonly<Record<string, string>>,
): string {
  const search = params ? new URLSearchParams(params).toString() : ''
  return `#${view}${section ? `/${section}` : ''}${search ? `?${search}` : ''}`
}

export function navigate(href: string): void {
  if (window.location.hash === href) notify()
  else window.location.hash = href
}
