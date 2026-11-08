// Ficha desplegable de una impresora: puerto, driver, red, serial y ubicación.

import type { Printer } from '@/application'
import {
  formatBool,
  plain,
  spec,
  specText,
} from '@/presentation/shared/formatters'
import type { SpecRow } from '@/presentation/shared/types'

export function printerDetail(printer: Printer): readonly SpecRow[] {
  const usb =
    printer.usbVendorId !== null
      ? `${printer.usbVendorId}:${printer.usbProductId ?? '????'}`
      : null
  return [
    spec('Driver (modelo)', printer.driverName),
    spec('Versión del driver', printer.driverVersion),
    spec('Puerto', printer.portName),
    spec('Puerto de red', printer.portNumber),
    spec('Protocolo', printer.protocol),
    spec('Número de serie', printer.serialNumber),
    ...(usb ? [specText('VID:PID USB', usb)] : []),
    spec('Compartida', printer.isShared, formatBool),
    spec('Nombre compartido', printer.shareName),
    spec('Ubicación', printer.location),
    spec('Comentario', printer.comment),
    { label: 'Nombre en Windows', value: plain(printer.name, true) },
  ]
}
