import {
  DataTable,
  Lede,
  SpecList,
  Toolbar,
  Value,
} from '@/presentation/shared/components'
import { ActionButton } from '@/presentation/support/components/ActionButton/ActionButton'
import { describe } from '@/presentation/shared/formatters'
import { byIndex } from '@/presentation/shared/utils/byIndex'
import { ModuleMissing } from '../../components/ModuleMissing/ModuleMissing'
import { NoInventory } from '../../components/NoInventory/NoInventory'
import {
  displayModeColumns,
  graphicsColumns,
  memoryModuleColumns,
  monitorColumns,
  networkColumns,
  problemDeviceColumns,
} from '../../formatters/hardwareColumns'
import {
  batterySpecs,
  identitySpecs,
  memorySpecs,
  processorSpecs,
  tpmSpecs,
} from '../../formatters/hardwareSpecs'
import { useHardware } from '../../hooks/useHardware'

export function HardwarePage() {
  const { inventory, device, hardware, devices, isThisDevice } = useHardware()
  if (!inventory || !hardware) {
    return (
      <>
        <h1>Hardware</h1>
        <NoInventory />
      </>
    )
  }
  const { processor, memory, graphics, displays, network, battery, tpm } =
    hardware
  return (
    <>
      <h1>Hardware</h1>

      <h2 id="identificacion" tabIndex={-1}>
        Identificación
      </h2>
      {device ? (
        <SpecList rows={identitySpecs(device)} />
      ) : (
        <ModuleMissing module="identity" label="identificación" />
      )}

      <h2 id="procesador" tabIndex={-1}>
        Procesador
      </h2>
      {processor ? (
        processor.processors.map((cpu, index) => (
          <SpecList key={index} rows={processorSpecs(cpu)} />
        ))
      ) : (
        <ModuleMissing module="processor" label="procesador" />
      )}

      <h2 id="memoria" tabIndex={-1}>
        Memoria
      </h2>
      {memory ? (
        <>
          <SpecList rows={memorySpecs(memory)} />
          <h3>Módulos instalados</h3>
          <DataTable
            columns={memoryModuleColumns}
            rows={memory.modules}
            rowKey={byIndex(memory.modules)}
            emptyText="SMBIOS no reportó módulos de memoria."
          />
        </>
      ) : (
        <ModuleMissing module="memory" label="memoria" />
      )}

      <h2 id="graficos" tabIndex={-1}>
        Tarjetas gráficas
      </h2>
      {graphics ? (
        <DataTable
          columns={graphicsColumns}
          rows={graphics.adapters}
          rowKey={byIndex(graphics.adapters)}
          emptyText="Windows no reportó tarjetas gráficas."
        />
      ) : (
        <ModuleMissing module="graphics" label="gráficos" />
      )}

      <h2 id="pantallas" tabIndex={-1}>
        Pantallas
      </h2>
      {displays ? (
        <>
          <DataTable
            columns={displayModeColumns}
            rows={displays.activeModes}
            rowKey={byIndex(displays.activeModes)}
            emptyText="No hay salidas de video activas."
          />
          {displays.monitors.length ? (
            <>
              <h3>Monitores detectados</h3>
              <DataTable
                columns={monitorColumns}
                rows={displays.monitors}
                rowKey={byIndex(displays.monitors)}
              />
            </>
          ) : null}
        </>
      ) : (
        <ModuleMissing module="displays" label="pantallas" />
      )}

      <h2 id="red" tabIndex={-1}>
        Adaptadores de red físicos
      </h2>
      {network ? (
        <DataTable
          columns={networkColumns}
          rows={network.adapters}
          rowKey={byIndex(network.adapters)}
          emptyText="No se detectaron adaptadores físicos."
        />
      ) : (
        <ModuleMissing module="network" label="red" />
      )}

      <h2 id="bateria" tabIndex={-1}>
        Batería
      </h2>
      {battery ? (
        battery.present ? (
          battery.batteries.map((item, index) => (
            <SpecList key={index} rows={batterySpecs(item)} />
          ))
        ) : (
          <Lede>Este equipo no reporta batería.</Lede>
        )
      ) : (
        <ModuleMissing module="battery" label="batería" />
      )}

      <h2 id="tpm" tabIndex={-1}>
        TPM
      </h2>
      {tpm ? (
        <SpecList rows={tpmSpecs(tpm)} />
      ) : (
        <ModuleMissing module="tpm" label="TPM" />
      )}

      <h2 id="dispositivos" tabIndex={-1}>
        Dispositivos con errores
      </h2>
      {devices ? (
        <>
          <Lede>
            Dispositivos detectados:{' '}
            <Value display={describe(devices.totalCount)} />. Con errores:{' '}
            {devices.problemCount}.
          </Lede>
          <DataTable
            columns={problemDeviceColumns}
            rows={devices.problems}
            rowKey={byIndex(devices.problems)}
            emptyText="Ningún dispositivo informa errores."
          />
          {isThisDevice ? (
            <Toolbar align="center">
              {/* En vivo: qué controlador falta y cómo arreglarlo, o instalar desde una carpeta. */}
              <ActionButton tool="drivers.missing" params={{}}>
                Revisar controladores que faltan
              </ActionButton>
              <ActionButton tool="drivers.install" params={{}}>
                Instalar controladores desde una carpeta
              </ActionButton>
            </Toolbar>
          ) : null}
        </>
      ) : (
        <ModuleMissing module="devices" label="dispositivos" />
      )}
    </>
  )
}
