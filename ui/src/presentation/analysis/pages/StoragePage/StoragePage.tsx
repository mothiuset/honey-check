import { DataTable, Lede } from '@/presentation/shared/components'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'
import { byIndex } from '@/presentation/shared/utils/byIndex'
import { ActionButton } from '@/presentation/support/components/ActionButton/ActionButton'
import { DiskCard } from '../../components/DiskCard/DiskCard'
import { ModuleMissing } from '../../components/ModuleMissing/ModuleMissing'
import { NoInventory } from '../../components/NoInventory/NoInventory'
import { excludedColumns } from '../../formatters/storageColumns'

export function StoragePage() {
  const { inventory, isThisDevice } = useCurrentInventory()
  const storage = inventory?.hardware.storage ?? null
  const external = storage?.external ?? []
  // Abrir la unidad corre al momento; analizarla abre Espacio en disco, que dice qué ocupa cada
  // carpeta: esta vista es el resumen, aquella el detalle.
  const actions = isThisDevice
    ? (letter: string) => (
        <>
          <ActionButton
            size="small"
            tool="explorer.open"
            params={{ path: `${letter}:\\` }}
          >
            Abrir
          </ActionButton>
          <ActionButton
            size="small"
            tool="disk.analyze"
            params={{ targets: `${letter}:\\` }}
          >
            Analizar espacio
          </ActionButton>
        </>
      )
    : null
  return (
    <>
      <h1>Almacenamiento</h1>
      <Lede>
        Los discos del equipo con sus unidades y lo que tienen libre, y los
        externos conectados al analizar. Para ver qué ocupa una unidad, use
        «Analizar espacio».
      </Lede>
      {!inventory ? <NoInventory /> : null}
      {inventory && !storage ? (
        <ModuleMissing module="storage" label="almacenamiento" />
      ) : null}
      {storage ? (
        <>
          {storage.disks.length ? null : (
            <Lede>No se detectaron discos internos.</Lede>
          )}
          {storage.disks.map((disk, index) => (
            <DiskCard
              key={index}
              disk={disk}
              anchor={`disco-${String(disk.number.value ?? index)}`}
              actions={actions}
            />
          ))}
          {external.length ? (
            <>
              <h2 id="externos" tabIndex={-1}>
                Discos externos ({external.length})
              </h2>
              <Lede>
                USB y tarjetas conectados al analizar. No son parte del equipo:
                su número de serie no se guarda.
              </Lede>
              {external.map((disk, index) => (
                <DiskCard
                  key={index}
                  disk={disk}
                  anchor={`externo-${String(disk.number.value ?? index)}`}
                  actions={actions}
                />
              ))}
            </>
          ) : null}
          {storage.excluded.length ? (
            <>
              <h2 id="excluidos" tabIndex={-1}>
                Discos virtuales y de red
              </h2>
              <DataTable
                columns={excludedColumns}
                rows={storage.excluded}
                rowKey={byIndex(storage.excluded)}
              />
            </>
          ) : null}
        </>
      ) : null}
    </>
  )
}
