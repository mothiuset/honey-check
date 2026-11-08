import type { SoftwareSection } from '@/application'
import { DataTable, Lede } from '@/presentation/shared/components'
import { ProgramSupportLinks } from '@/presentation/support/components/SupportLinks/SupportLinks'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'
import { ModuleMissing } from '../../components/ModuleMissing/ModuleMissing'
import { NoInventory } from '../../components/NoInventory/NoInventory'
import { ProgramDetail } from '../../components/ProgramDetail/ProgramDetail'
import { SoftwareFilters } from '../../components/SoftwareFilters/SoftwareFilters'
import {
  softwareColumns,
  sourceColumns,
} from '../../formatters/softwareColumns'
import { useSoftwareFilter } from '../../hooks/useSoftwareFilter'

const NO_ITEMS: SoftwareSection['items'] = []

export function SoftwarePage() {
  const { inventory, isThisDevice } = useCurrentInventory()
  const software = inventory?.software ?? null
  const { filter, visible, declaredSize, update } = useSoftwareFilter(
    software?.items ?? NO_ITEMS,
  )

  if (!inventory || !software) {
    return (
      <>
        <h1>Software</h1>
        {inventory ? (
          <ModuleMissing module="software" label="software" />
        ) : (
          <NoInventory />
        )}
      </>
    )
  }

  return (
    <>
      <h1>Software</h1>
      <SoftwareFilters filter={filter} onChange={update} />
      <Lede live>
        {visible.length} de {software.totalCount} programas
        {declaredSize ? `, ${declaredSize} declarados` : ''}
      </Lede>
      <DataTable
        columns={softwareColumns}
        rows={visible}
        rowKey={(item) => item.id}
        renderExpanded={(item) => (
          <>
            <ProgramDetail item={item} />
            {isThisDevice ? <ProgramSupportLinks item={item} /> : null}
          </>
        )}
        emptyText="Ningún programa coincide con la búsqueda."
      />

      <h2 id="fuentes" tabIndex={-1}>
        Fuentes consultadas
      </h2>
      <DataTable
        columns={sourceColumns}
        rows={software.sources}
        rowKey={(source) => source.source}
      />

      <h2 id="limites" tabIndex={-1}>
        Qué no puede detectarse
      </h2>
      <ul>
        {software.limitations.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </>
  )
}
