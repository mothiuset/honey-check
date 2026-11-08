import type { DisconnectedPeripheral } from '@/application'
import {
  Check,
  DataTable,
  Lede,
  SpecList,
  Toolbar,
} from '@/presentation/shared/components'
import { ActionButton } from '@/presentation/support/components/ActionButton/ActionButton'
import { PrinterSupportLinks } from '@/presentation/support/components/SupportLinks/SupportLinks'
import { DeviceParts } from '../../components/DeviceParts'
import { ModuleMissing } from '../../components/ModuleMissing/ModuleMissing'
import { NoInventory } from '../../components/NoInventory/NoInventory'
import {
  disconnectedColumns,
  peripheralColumns,
  printerColumns,
} from '../../formatters/peripheralColumns'
import { printerDetail } from '../../formatters/printerDetail'
import { usePeripherals } from '../../hooks/usePeripherals'

// Una parte cualquiera basta: la herramienta vuelve a leer el aparato completo del equipo.
const handle = (device: DisconnectedPeripheral) =>
  device.parts[0]?.instanceId ?? ''

const keyOf = (device: DisconnectedPeripheral) =>
  `${device.state}-${handle(device)}-${device.name ?? ''}`

export function PeripheralsPage() {
  const view = usePeripherals()
  const { section } = view

  if (!view.inventory || !section) {
    return (
      <>
        <h1>Periféricos e impresoras</h1>
        {view.inventory ? (
          <ModuleMissing module="peripherals" label="periféricos" />
        ) : (
          <NoInventory />
        )}
      </>
    )
  }

  const forget = view.isThisDevice
    ? (device: DisconnectedPeripheral) => (
        <ActionButton
          size="small"
          tool="bluetooth.forget"
          params={{ devices: handle(device) }}
        >
          Olvidar
        </ActionButton>
      )
    : null
  const remove = view.isThisDevice
    ? (device: DisconnectedPeripheral) => (
        <ActionButton
          size="small"
          tone="danger"
          tool="devices.remove_leftovers"
          params={{ devices: handle(device) }}
        >
          Quitar
        </ActionButton>
      )
    : null

  return (
    <>
      <h1>Periféricos e impresoras</h1>
      <Lede>
        Cada aparato una sola vez, con todo lo que hace. El serial y los
        consumibles de una impresora de red se consultan aparte, desde Soporte.
      </Lede>

      <h2 id="impresoras" tabIndex={-1}>
        Impresoras
      </h2>
      <DataTable
        columns={printerColumns}
        rows={section.printers}
        rowKey={(printer) => printer.name}
        renderExpanded={(printer) => (
          <>
            <SpecList rows={printerDetail(printer)} />
            {view.isThisDevice ? (
              <PrinterSupportLinks printer={printer} />
            ) : null}
          </>
        )}
        emptyText="No hay impresoras instaladas."
      />

      <h2 id="dispositivos" tabIndex={-1}>
        Conectados
      </h2>
      {view.hiddenComponents ? (
        <Toolbar align="center">
          <Check
            label={`Mostrar componentes HID (${String(view.hiddenComponents)})`}
            checked={view.showComponents}
            onChange={view.setShowComponents}
          />
        </Toolbar>
      ) : null}
      {view.groups.length ? null : <Lede>No se detectaron periféricos.</Lede>}
      {view.groups.map((group) => (
        <section key={group.category}>
          <h3>
            {group.label} ({group.devices.length})
          </h3>
          <DataTable
            columns={peripheralColumns}
            rows={group.devices}
            rowKey={(device) => device.instanceId ?? device.name.value ?? ''}
            renderExpanded={(device) => (
              <DeviceParts parts={device.parts ?? []} />
            )}
          />
        </section>
      ))}

      <h2 id="no-conectados" tabIndex={-1}>
        No conectados
      </h2>
      {view.oldFormat ? (
        <Lede>
          Este análisis es de una versión anterior: analice el equipo de nuevo
          para ver lo que Windows recuerda sin estar conectado.
        </Lede>
      ) : null}
      {view.paired.length ? (
        <section aria-labelledby="emparejados">
          <h3 id="emparejados">
            Emparejados por Bluetooth ({view.paired.length})
          </h3>
          <Lede>
            Apagados o lejos. Siguen emparejados: «Olvidar» los desempareja y
            para usarlos otra vez hay que emparejarlos de nuevo.
          </Lede>
          <DataTable
            columns={disconnectedColumns(forget)}
            rows={view.paired}
            rowKey={keyOf}
            renderExpanded={(device) => <DeviceParts parts={device.parts} />}
          />
        </section>
      ) : null}
      {view.leftovers.length ? (
        <section aria-labelledby="restos">
          <h3 id="restos">Ya no están ({view.leftovers.length})</h3>
          <Lede>
            Se conectaron alguna vez y Windows los sigue recordando. Quitarlos
            no afecta nada: si vuelve a conectar uno, Windows lo reconoce solo.
            Antes de quitar se respaldan sus controladores, y se pueden
            restaurar.
          </Lede>
          {view.isThisDevice && view.leftovers.length > 1 ? (
            <Toolbar align="center">
              <ActionButton
                tone="danger"
                tool="devices.remove_leftovers"
                params={{ devices: view.leftovers.map(handle).join('\n') }}
              >
                Quitar todos ({view.leftovers.length})
              </ActionButton>
            </Toolbar>
          ) : null}
          <DataTable
            columns={disconnectedColumns(remove)}
            rows={view.leftovers}
            rowKey={keyOf}
            renderExpanded={(device) => <DeviceParts parts={device.parts} />}
          />
        </section>
      ) : null}
      {!view.oldFormat && !view.paired.length && !view.leftovers.length ? (
        <Lede>Windows no recuerda aparatos que no estén conectados.</Lede>
      ) : null}
    </>
  )
}
