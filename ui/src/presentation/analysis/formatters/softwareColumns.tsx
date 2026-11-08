import type { SoftwareItem, SoftwareSection } from '@/application'
import { Value, type Column } from '@/presentation/shared/components'
import {
  SOURCE_STATUS,
  describe,
  describeQuiet,
  formatBytes,
  formatDay,
} from '@/presentation/shared/formatters'
import { ProgramName } from '../components/ProgramName/ProgramName'

type Source = SoftwareSection['sources'][number]

export const softwareColumns: readonly Column<SoftwareItem>[] = [
  {
    key: 'name',
    label: 'Programa',
    sortable: true,
    value: (i) => i.name,
    render: (i) => <ProgramName item={i} />,
  },
  {
    key: 'version',
    label: 'Versión',
    sortable: true,
    value: (i) => i.version.value,
    render: (i) => <Value display={describeQuiet(i.version)} />,
  },
  {
    key: 'publisher',
    label: 'Editor',
    priority: 2,
    sortable: true,
    value: (i) => i.publisher.value,
    render: (i) => <Value display={describeQuiet(i.publisher)} />,
  },
  {
    key: 'size',
    label: 'Tamaño',
    priority: 2,
    align: 'end',
    sortable: true,
    value: (i) => i.sizeBytes.value,
    render: (i) => <Value display={describeQuiet(i.sizeBytes, formatBytes)} />,
  },
  {
    key: 'arch',
    label: 'Arquitectura',
    priority: 3,
    sortable: true,
    value: (i) => i.architecture.value,
    render: (i) => <Value display={describe(i.architecture)} />,
  },
  {
    key: 'date',
    label: 'Instalado',
    priority: 3,
    sortable: true,
    value: (i) => i.installDate.value,
    render: (i) => <Value display={describe(i.installDate, formatDay)} />,
  },
]

export const sourceColumns: readonly Column<Source>[] = [
  { key: 'source', label: 'Fuente', value: (s) => s.source },
  {
    key: 'status',
    label: 'Estado',
    value: (s) => SOURCE_STATUS[s.status] ?? s.status,
  },
  { key: 'count', label: 'Programas', align: 'end', value: (s) => s.itemCount },
  {
    key: 'detail',
    label: 'Detalle',
    priority: 3,
    value: (s) => s.detail ?? '',
  },
]
