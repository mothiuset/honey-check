import { Check, Field, Toolbar } from '@/presentation/shared/components'
import { INSTALLERS } from '@/presentation/shared/formatters'
import type { SoftwareFilter } from '../../formatters/filterSoftware'
import type { SoftwareScopeFilter } from '../../types/analysis.types'

export interface SoftwareFiltersProps {
  readonly filter: SoftwareFilter
  readonly onChange: (patch: Partial<SoftwareFilter>) => void
}

const SCOPE_OPTIONS: readonly (readonly [SoftwareScopeFilter, string])[] = [
  ['', 'Todos'],
  ['machine', 'Todo el equipo'],
  ['current_user', 'Usuario actual'],
]

export function SoftwareFilters({ filter, onChange }: SoftwareFiltersProps) {
  return (
    <Toolbar>
      <Field label="Buscar" grow>
        <input
          type="search"
          value={filter.search}
          placeholder="Nombre, editor, versión o ruta"
          aria-label="Buscar programas"
          onChange={(event) => {
            onChange({ search: event.target.value })
          }}
        />
      </Field>
      <Field label="Instalado para">
        <select
          value={filter.scope}
          aria-label="Instalado para"
          onChange={(event) => {
            onChange({ scope: event.target.value as SoftwareScopeFilter })
          }}
        >
          {SCOPE_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Tipo">
        <select
          value={filter.installer}
          aria-label="Tipo de instalación"
          onChange={(event) => {
            onChange({ installer: event.target.value })
          }}
        >
          <option value="">Todos</option>
          {Object.entries(INSTALLERS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Check
        label="Incluir componentes del sistema"
        checked={filter.showSystem}
        onChange={(showSystem) => {
          onChange({ showSystem })
        }}
      />
    </Toolbar>
  )
}
