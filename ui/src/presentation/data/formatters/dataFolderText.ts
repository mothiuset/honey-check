import type { Workspace } from '@/application'
import { specText } from '@/presentation/shared/formatters'
import type { SpecRow } from '@/presentation/shared/types'

const REJECTED: Readonly<Record<string, string>> = {
  invalid_path: 'La ruta no es válida.',
  network_path_not_allowed:
    'Honey Check no guarda en rutas de red. Elija una carpeta local.',
  path_must_be_absolute: 'Escriba la ruta completa, con la letra de unidad.',
  directory_not_found: 'Esa carpeta no existe. Créela o elija otra.',
  not_writable: 'Esa carpeta no permite escribir. Elija otra.',
}

export const exportRejection = (reason: string): string =>
  REJECTED[reason] ?? 'No se pudo guardar.'

export function workspaceState(workspace: Workspace | null): string | null {
  if (!workspace) return null
  if (workspace.writable) return 'Disponible para escribir'
  return workspace.available ? 'No permite escribir' : 'No disponible'
}

/** Cómo se lee la confianza de cada dato. */
export const READING_GUIDE: readonly SpecRow[] = [
  specText('Sin etiqueta', 'Lo informó Windows, SMBIOS o el Registro.'),
  specText(
    'verificado',
    'Comprobado contra el propio archivo, como la cabecera del ejecutable.',
  ),
  specText(
    'calculado',
    'Obtenido con una regla fija a partir de datos de Windows.',
  ),
  specText('probable', 'Candidato deducido: puede no ser correcto.'),
  specText('Sin dato', 'No se pudo determinar. Al lado aparece el motivo.'),
]
