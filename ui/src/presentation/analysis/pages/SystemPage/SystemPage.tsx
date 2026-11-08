import { DataTable, Lede, SpecList } from '@/presentation/shared/components'
import { formatSeconds } from '@/presentation/shared/formatters'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'
import { ModuleMissing } from '../../components/ModuleMissing/ModuleMissing'
import { NoInventory } from '../../components/NoInventory/NoInventory'
import { hotfixColumns, moduleColumns } from '../../formatters/systemColumns'
import { operatingSystemSpecs } from '../../formatters/systemSpecs'

export function SystemPage() {
  const { inventory } = useCurrentInventory()
  if (!inventory) {
    return (
      <>
        <h1>Sistema</h1>
        <NoInventory />
      </>
    )
  }
  const os = inventory.operatingSystem
  return (
    <>
      <h1>Sistema</h1>
      {os ? (
        <SpecList rows={operatingSystemSpecs(os)} />
      ) : (
        <ModuleMissing module="operating_system" label="sistema operativo" />
      )}
      {os?.hotfixes.length ? (
        <>
          <h2 id="actualizaciones" tabIndex={-1}>
            Actualizaciones instaladas
          </h2>
          <DataTable
            columns={hotfixColumns}
            rows={os.hotfixes}
            rowKey={(hotfix) => hotfix.id}
          />
        </>
      ) : null}
      <h2 id="duracion" tabIndex={-1}>
        Duración del análisis
      </h2>
      <Lede>Total: {formatSeconds(inventory.collection.durationMs)}.</Lede>
      <DataTable
        columns={moduleColumns}
        rows={inventory.modules}
        rowKey={(module) => module.name}
      />
    </>
  )
}
