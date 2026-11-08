import type { HotFix, ModuleReport, SecuritySection } from '@/application'
import { Value, type Column } from '@/presentation/shared/components'
import {
  MODULE_LABELS,
  MODULE_STATUS,
  describe,
  formatBool,
  formatDate,
  formatSeconds,
} from '@/presentation/shared/formatters'

type Product = SecuritySection['antivirus'][number]
type Firewall = SecuritySection['firewallProfiles'][number]
type Encryption = SecuritySection['volumeEncryption'][number]

export const hotfixColumns: readonly Column<HotFix>[] = [
  { key: 'id', label: 'Identificador', sortable: true, value: (h) => h.id },
  {
    key: 'type',
    label: 'Tipo',
    priority: 2,
    sortable: true,
    value: (h) => h.description ?? '',
  },
  {
    key: 'date',
    label: 'Fecha',
    sortable: true,
    value: (h) => h.installedOnRaw,
    render: (h) =>
      h.installedOnRaw ? formatDate(h.installedOnRaw, false) : 'Sin dato',
  },
]

export const moduleColumns: readonly Column<ModuleReport>[] = [
  {
    key: 'name',
    label: 'Módulo',
    sortable: true,
    value: (m) => MODULE_LABELS[m.name] ?? m.name,
  },
  {
    key: 'status',
    label: 'Estado',
    sortable: true,
    value: (m) => MODULE_STATUS[m.status] ?? m.status,
  },
  {
    key: 'duration',
    label: 'Duración',
    align: 'end',
    sortable: true,
    value: (m) => m.durationMs,
    render: (m) => formatSeconds(m.durationMs),
  },
  {
    key: 'retries',
    label: 'Reintentos',
    priority: 3,
    align: 'end',
    value: (m) => m.retries,
  },
]

export const antivirusColumns: readonly Column<Product>[] = [
  { key: 'name', label: 'Producto', value: (a) => a.name.value },
  {
    key: 'enabled',
    label: 'Activo',
    render: (a) => <Value display={describe(a.enabled, formatBool)} />,
  },
  {
    key: 'current',
    label: 'Firmas al día',
    render: (a) => <Value display={describe(a.upToDate, formatBool)} />,
  },
  {
    key: 'path',
    label: 'Ejecutable',
    priority: 3,
    value: (a) => a.executablePath.value,
  },
]

export const firewallColumns: readonly Column<Firewall>[] = [
  { key: 'name', label: 'Perfil', value: (f) => f.name },
  {
    key: 'enabled',
    label: 'Habilitado',
    render: (f) => <Value display={describe(f.enabled, formatBool)} />,
  },
]

export const encryptionColumns: readonly Column<Encryption>[] = [
  { key: 'drive', label: 'Unidad', value: (v) => `${v.driveLetter}:` },
  {
    key: 'protection',
    label: 'Protección',
    render: (v) => <Value display={describe(v.protection)} />,
  },
]
