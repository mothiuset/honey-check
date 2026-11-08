// Accesos a Soporte desde las vistas del inventario: lo que se puede hacer con lo que se está viendo.

import type { Printer, SoftwareItem } from '@/application'
import { Toolbar } from '@/presentation/shared/components'
import { ActionButton } from '../ActionButton/ActionButton'

export function PrinterSupportLinks({ printer }: { printer: Printer }) {
  const host = printer.hostAddress.value
  return (
    <Toolbar align="center">
      {host ? (
        <ActionButton
          size="small"
          tone="primary"
          tool="printers.snmp"
          params={{ host }}
        >
          Consultar serial, contador y consumibles
        </ActionButton>
      ) : null}
      <ActionButton
        size="small"
        tool="printers.test_page"
        params={{ printer: printer.name }}
      >
        Imprimir página de prueba
      </ActionButton>
      {printer.isDefault.value ? null : (
        <ActionButton
          size="small"
          tool="printers.set_default"
          params={{ printer: printer.name }}
        >
          Dejar como predeterminada
        </ActionButton>
      )}
      <ActionButton size="small" tool="printers.clear_queue" params={{}}>
        Vaciar la cola
      </ActionButton>
    </Toolbar>
  )
}

/** Solo para programas de este equipo: el servicio los busca en su último análisis. */
export function ProgramSupportLinks({ item }: { item: SoftwareItem }) {
  return (
    <Toolbar align="center">
      <ActionButton
        size="small"
        tone="danger"
        tool="software.uninstall"
        params={{ software: item.id }}
      >
        Desinstalar
      </ActionButton>
      <ActionButton
        size="small"
        tool="software.leftovers"
        params={{ software: item.id }}
      >
        Buscar restos
      </ActionButton>
    </Toolbar>
  )
}
