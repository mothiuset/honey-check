// Columnas de las tablas de hardware.

import type {
  DisplayMode,
  GraphicsAdapter,
  MemoryModule,
  Monitor,
  NetworkAdapter,
  ProblemDevice,
} from '@/application'
import { Value, type Column } from '@/presentation/shared/components'
import {
  describe,
  describeQuiet,
  formatBytes,
  formatDay,
  formatMts,
  formatSpeed,
} from '@/presentation/shared/formatters'

export const memoryModuleColumns: readonly Column<MemoryModule>[] = [
  { key: 'slot', label: 'Ranura', sortable: true, value: (m) => m.slot.value },
  {
    key: 'capacity',
    label: 'Capacidad',
    align: 'end',
    sortable: true,
    value: (m) => m.capacityBytes.value,
    render: (m) => (
      <Value display={describeQuiet(m.capacityBytes, formatBytes)} />
    ),
  },
  {
    key: 'type',
    label: 'Tipo',
    sortable: true,
    value: (m) => m.memoryType.value,
    render: (m) => <Value display={describe(m.memoryType)} />,
  },
  {
    key: 'speed',
    label: 'Velocidad',
    priority: 2,
    align: 'end',
    sortable: true,
    value: (m) => m.speedMts.value,
    render: (m) => <Value display={describeQuiet(m.speedMts, formatMts)} />,
  },
  {
    key: 'manufacturer',
    label: 'Fabricante',
    priority: 3,
    value: (m) => m.manufacturer.value,
  },
  {
    key: 'part',
    label: 'Número de parte',
    priority: 3,
    value: (m) => m.partNumber.value,
  },
  {
    key: 'form',
    label: 'Formato',
    priority: 3,
    value: (m) => m.formFactor.value,
  },
]

export const graphicsColumns: readonly Column<GraphicsAdapter>[] = [
  { key: 'name', label: 'Nombre', sortable: true, value: (g) => g.name.value },
  {
    key: 'memory',
    label: 'Memoria',
    align: 'end',
    value: (g) => g.memoryBytes.value,
    render: (g) => (
      <Value display={describeQuiet(g.memoryBytes, formatBytes)} />
    ),
  },
  {
    key: 'driver',
    label: 'Controlador',
    priority: 2,
    value: (g) => g.driverVersion.value,
  },
  {
    key: 'date',
    label: 'Fecha del controlador',
    priority: 3,
    value: (g) => g.driverDate.value,
    render: (g) => <Value display={describeQuiet(g.driverDate, formatDay)} />,
  },
  {
    key: 'resolution',
    label: 'Resolución',
    priority: 3,
    value: (g) =>
      g.currentWidthPixels.value && g.currentHeightPixels.value
        ? `${String(g.currentWidthPixels.value)} × ${String(g.currentHeightPixels.value)}`
        : null,
  },
  { key: 'status', label: 'Estado', priority: 2, value: (g) => g.status.value },
]

export const displayModeColumns: readonly Column<DisplayMode>[] = [
  { key: 'device', label: 'Salida', value: (d) => d.device },
  {
    key: 'resolution',
    label: 'Resolución',
    value: (d) => `${String(d.widthPixels)} × ${String(d.heightPixels)}`,
  },
  {
    key: 'refresh',
    label: 'Frecuencia',
    align: 'end',
    value: (d) => (d.refreshHz ? `${String(d.refreshHz)} Hz` : 'Sin dato'),
  },
  {
    key: 'primary',
    label: 'Principal',
    value: (d) => (d.isPrimary ? 'Sí' : 'No'),
  },
]

export const monitorColumns: readonly Column<Monitor>[] = [
  { key: 'model', label: 'Modelo', value: (m) => m.model.value },
  { key: 'maker', label: 'Fabricante', value: (m) => m.manufacturerCode.value },
  {
    key: 'serial',
    label: 'Serie',
    priority: 2,
    value: (m) => m.serialNumber.value,
  },
  {
    key: 'year',
    label: 'Año',
    priority: 3,
    align: 'end',
    value: (m) => m.yearOfManufacture.value,
  },
]

export const networkColumns: readonly Column<NetworkAdapter>[] = [
  { key: 'name', label: 'Nombre', sortable: true, value: (n) => n.name.value },
  {
    key: 'description',
    label: 'Descripción',
    priority: 2,
    value: (n) => n.description.value,
  },
  { key: 'mac', label: 'MAC', priority: 3, value: (n) => n.macAddress.value },
  {
    key: 'connection',
    label: 'Conexión',
    value: (n) =>
      n.connection.value === 'connected'
        ? 'Conectado'
        : n.connection.value
          ? 'Desconectado'
          : null,
  },
  {
    key: 'speed',
    label: 'Velocidad',
    priority: 2,
    align: 'end',
    value: (n) => n.linkSpeedBitsPerSecond.value,
    render: (n) => (
      <Value display={describeQuiet(n.linkSpeedBitsPerSecond, formatSpeed)} />
    ),
  },
  {
    key: 'ipv4',
    label: 'IPv4',
    priority: 3,
    value: (n) => n.ipv4Addresses.join(', ') || 'Ninguna',
  },
]

export const problemDeviceColumns: readonly Column<ProblemDevice>[] = [
  {
    key: 'name',
    label: 'Dispositivo',
    sortable: true,
    value: (d) => d.name.value,
  },
  {
    key: 'class',
    label: 'Clase',
    priority: 3,
    sortable: true,
    value: (d) => d.deviceClass.value,
  },
  {
    key: 'code',
    label: 'Código',
    priority: 2,
    align: 'end',
    sortable: true,
    value: (d) => d.errorCode,
  },
  {
    key: 'problem',
    label: 'Problema',
    value: (d) => d.errorDescription ?? 'Código sin descripción conocida',
  },
]
