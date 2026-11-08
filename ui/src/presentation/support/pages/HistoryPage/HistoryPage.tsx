import type { Run } from '@/application'
import {
  Button,
  DataTable,
  Lede,
  Tag,
  Toolbar,
  type Column,
} from '@/presentation/shared/components'
import { formatDate } from '@/presentation/shared/formatters'
import { useOpenFolder } from '@/presentation/shared/hooks/useOpenFolder'
import { RouteLink } from '@/presentation/shared/navigation'
import { ResultView } from '../../components/ResultView/ResultView'
import { RunView } from '../../components/RunView/RunView'
import { HISTORY_VIEW, runHref } from '../../formatters/supportRoutes'
import { duration, RISKS, RUN_STATES } from '../../formatters/supportText'
import { useSupportHistory } from '../../hooks/useSupportHistory'

const columns: readonly Column<Run>[] = [
  {
    key: 'when',
    label: 'Inicio',
    sortable: true,
    value: (run) => run.startedAt,
    render: (run) => (
      <RouteLink href={runHref(run.id)}>{formatDate(run.startedAt)}</RouteLink>
    ),
  },
  {
    key: 'title',
    label: 'Herramienta',
    sortable: true,
    value: (run) => run.title,
  },
  {
    key: 'status',
    label: 'Estado',
    sortable: true,
    value: (run) => run.status,
    render: (run) => (
      <Tag tone={RUN_STATES[run.status].tone}>
        {RUN_STATES[run.status].label}
      </Tag>
    ),
  },
  {
    key: 'risk',
    label: 'Tipo',
    priority: 2,
    value: (run) => RISKS[run.risk].label,
  },
  {
    key: 'duration',
    label: 'Duración',
    priority: 3,
    align: 'end',
    value: (run) => duration(run.startedAt, run.finishedAt),
  },
]

export function HistoryPage() {
  const view = useSupportHistory()
  const openFolder = useOpenFolder()

  if (view.runId)
    return (
      <>
        <RouteLink href={`#${HISTORY_VIEW}`}>Volver al historial</RouteLink>
        <h1>{view.run?.title ?? 'Ejecución'}</h1>
        {view.run ? (
          <>
            <RunView run={view.run} onCancel={view.cancel} />
            {view.run.result ? (
              <ResultView result={view.run.result} onOpenFolder={openFolder} />
            ) : null}
          </>
        ) : (
          <Lede live>Cargando la ejecución.</Lede>
        )}
      </>
    )

  return (
    <>
      <h1>Historial de soporte</h1>
      <Lede>
        Cada herramienta ejecutada, con sus comandos, su salida y su resultado.
        También se guarda en HoneyCheck-datos\acciones; los respaldos, en
        HoneyCheck-datos\respaldos.
      </Lede>
      <Toolbar align="center">
        <Button
          size="small"
          onClick={() => {
            openFolder('acciones')
          }}
        >
          Abrir la carpeta de acciones
        </Button>
        <Button
          size="small"
          onClick={() => {
            openFolder('respaldos')
          }}
        >
          Abrir la carpeta de respaldos
        </Button>
      </Toolbar>
      <DataTable
        columns={columns}
        rows={view.history ?? []}
        rowKey={(run) => run.id}
        loading={view.history === null}
        emptyText="Todavía no se ejecutó ninguna herramienta."
      />
    </>
  )
}
