// El servicio marca los parámetros que son rutas (`browse` en su definición); la interfaz los
// muestra con «Elegir…», que abre el diálogo de Windows. Es una indicación de presentación: el
// dominio de la interfaz no la modela.

import type { ToolParam } from '@/application'

export interface PathBrowse {
  readonly kind: 'folder' | 'file'
  readonly filter: string | null
}

export function browseOf(param: ToolParam): PathBrowse | null {
  const raw = param as ToolParam & {
    readonly browse?: unknown
    readonly browseFilter?: unknown
  }
  if (raw.browse !== 'folder' && raw.browse !== 'file') return null
  return {
    kind: raw.browse,
    filter: typeof raw.browseFilter === 'string' ? raw.browseFilter : null,
  }
}
