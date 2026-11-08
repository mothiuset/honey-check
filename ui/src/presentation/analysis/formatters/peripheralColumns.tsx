import type { ReactNode } from 'react'
import type { DisconnectedPeripheral, Peripheral, Printer } from '@/application'
import { Tag, Value, type Column } from '@/presentation/shared/components'
import {
  PERIPHERAL_CONNECTIONS,
  PERIPHERAL_FUNCTIONS,
  PRINTER_CONNECTIONS,
  PRINTER_ERRORS,
  PRINTER_STATUS,
  describe,
  describeQuiet,
  formatDay,
} from '@/presentation/shared/formatters'
import styles from './peripheralColumns.module.css'

const label =
  (map: Readonly<Record<string, string>>) =>
  (value: string): string =>
    map[value] ?? value

export const printerColumns: readonly Column<Printer>[] = [
  {
    key: 'name',
    label: 'Impresora',
    sortable: true,
    value: (p) => p.name,
    render: (p) => (
      <>
        {p.name}
        {p.isDefault.value ? <Tag tone="honey">predeterminada</Tag> : null}
      </>
    ),
  },
  {
    key: 'connection',
    label: 'Conexión',
    sortable: true,
    value: (p) => PRINTER_CONNECTIONS[p.connection] ?? p.connection,
  },
  {
    key: 'address',
    label: 'Dirección',
    sortable: true,
    value: (p) => p.hostAddress.value,
    render: (p) => <Value display={describeQuiet(p.hostAddress)} />,
  },
  {
    key: 'maker',
    label: 'Fabricante',
    priority: 2,
    value: (p) => p.manufacturer.value,
    render: (p) => <Value display={describeQuiet(p.manufacturer)} />,
  },
  {
    key: 'status',
    label: 'Estado',
    priority: 2,
    value: (p) => p.status.value,
    render: (p) => (
      <>
        <Value display={describeQuiet(p.status, label(PRINTER_STATUS))} />
        {p.detectedError.value ? (
          <Tag tone="bad">
            {PRINTER_ERRORS[p.detectedError.value] ?? p.detectedError.value}
          </Tag>
        ) : null}
      </>
    ),
  },
  {
    key: 'queue',
    label: 'En cola',
    priority: 3,
    align: 'end',
    value: (p) => p.queuedJobs.value,
  },
]

// Funciones con nombre femenino: «Pantalla integrada», «Cámara integrada».
const FEMININE = new Set(['display', 'camera', 'printer'])

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/**
 * El nombre del aparato. Si Windows solo da uno genérico («I2C HID Device»), se dice qué es por
 * su función principal: «Touchpad integrado», «Teclado integrado».
 */
export function deviceTitle(device: {
  readonly name: string | null
  readonly genericName?: boolean
  readonly functions?: readonly string[]
  readonly connection: string
}): string {
  const main = device.functions?.[0]
  if ((device.genericName || !device.name) && main) {
    const what = capital(PERIPHERAL_FUNCTIONS[main] ?? main)
    if (device.connection !== 'internal') return what
    return `${what} ${FEMININE.has(main) ? 'integrada' : 'integrado'}`
  }
  return device.name ?? 'Aparato sin nombre'
}

/** Lo que hace, en una línea: «teclado, mouse, teclas multimedia». */
export const functionsText = (functions: readonly string[] | undefined) =>
  (functions ?? []).map((f) => PERIPHERAL_FUNCTIONS[f] ?? f).join(', ')

function DeviceName({
  title,
  functions,
  children,
}: {
  title: string
  functions: string
  children?: ReactNode
}) {
  return (
    <span className={styles.device}>
      <span className={styles.title}>
        {title}
        {children}
      </span>
      {functions ? <span className={styles.functions}>{functions}</span> : null}
    </span>
  )
}

export const peripheralColumns: readonly Column<Peripheral>[] = [
  {
    key: 'name',
    label: 'Aparato',
    sortable: true,
    value: (d) => deviceTitle({ ...d, name: d.name.value }),
    render: (d) => (
      <DeviceName
        title={deviceTitle({ ...d, name: d.name.value })}
        functions={functionsText(d.functions)}
      >
        {d.errorCode ? <Tag tone="bad">error {d.errorCode}</Tag> : null}
      </DeviceName>
    ),
  },
  {
    key: 'maker',
    label: 'Fabricante',
    sortable: true,
    value: (d) => d.vendorName.value ?? d.manufacturer.value,
    render: (d) => (
      <Value
        display={
          d.vendorName.value
            ? describe(d.vendorName)
            : describeQuiet(d.manufacturer)
        }
      />
    ),
  },
  {
    key: 'connection',
    label: 'Conexión',
    priority: 2,
    sortable: true,
    value: (d) => PERIPHERAL_CONNECTIONS[d.connection] ?? d.connection,
  },
  {
    key: 'serial',
    label: 'Serial o MAC',
    priority: 2,
    value: (d) => d.serialNumber.value,
    render: (d) => <Value display={describeQuiet(d.serialNumber)} />,
  },
  {
    key: 'ids',
    label: 'VID:PID',
    priority: 3,
    value: (d) => (d.vendorId ? `${d.vendorId}:${d.productId ?? '????'}` : ''),
  },
  {
    key: 'driver',
    label: 'Driver',
    priority: 3,
    value: (d) => d.driverVersion.value,
    render: (d) => (
      <Value
        display={describeQuiet(
          d.driverVersion,
          (version) =>
            `${version}${d.driverDate.value ? ` (${formatDay(d.driverDate.value)})` : ''}`,
        )}
      />
    ),
  },
]

/** Aparatos que Windows recuerda sin estar conectados; `actions` solo en el análisis de este equipo. */
export function disconnectedColumns(
  actions: ((device: DisconnectedPeripheral) => ReactNode) | null,
): readonly Column<DisconnectedPeripheral>[] {
  const columns: Column<DisconnectedPeripheral>[] = [
    {
      key: 'name',
      label: 'Aparato',
      sortable: true,
      value: (d) => deviceTitle(d),
      render: (d) => (
        <DeviceName
          title={deviceTitle(d)}
          functions={functionsText(d.functions)}
        >
          {d.alsoConnected ? (
            <Tag tone="honey">conectado ahora en otro puerto</Tag>
          ) : null}
        </DeviceName>
      ),
    },
    {
      key: 'connection',
      label: 'Conexión',
      priority: 2,
      sortable: true,
      value: (d) => PERIPHERAL_CONNECTIONS[d.connection] ?? d.connection,
    },
    {
      key: 'seen',
      label: 'Última vez',
      sortable: true,
      value: (d) => d.lastSeenAt,
      render: (d) => (d.lastSeenAt ? formatDay(d.lastSeenAt) : 'Sin dato'),
    },
  ]
  if (actions)
    columns.push({ key: '__actions', label: 'Acciones', render: actions })
  return columns
}
