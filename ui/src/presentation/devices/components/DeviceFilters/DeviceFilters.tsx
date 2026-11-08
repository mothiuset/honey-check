import { Field, Toolbar } from '@/presentation/shared/components'
import type { DeviceFiltersProps } from './DeviceFilters.types'

export function DeviceFilters({
  text,
  query,
  filters,
  onSearch,
  onFilter,
}: DeviceFiltersProps) {
  return (
    <Toolbar>
      <Field label="Buscar" grow>
        <input
          type="search"
          value={text}
          placeholder="Nombre, serial, modelo, sistema o dominio"
          aria-label="Buscar equipos"
          onChange={(event) => {
            onSearch(event.target.value)
          }}
        />
      </Field>
      {filters.map((facet) => (
        <Field key={facet.key} label={facet.label}>
          <select
            value={query[facet.key]}
            aria-label={facet.label}
            onChange={(event) => {
              onFilter(facet.key, event.target.value)
            }}
          >
            <option value="">Todos</option>
            {facet.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
      ))}
    </Toolbar>
  )
}
