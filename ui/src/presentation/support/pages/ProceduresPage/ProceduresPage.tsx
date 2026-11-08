import type { Procedure, ProcedureRun } from '@/application'
import {
  Button,
  DataTable,
  Lede,
  LinkButton,
  Notice,
  Tag,
  Toolbar,
  type Column,
} from '@/presentation/shared/components'
import { formatDate } from '@/presentation/shared/formatters'
import { toolHref } from '../../formatters/supportRoutes'
import { useProcedures } from '../../hooks/useProcedures'
import styles from './ProceduresPage.module.css'

const STEP_KINDS: readonly [string, string][] = [
  [
    'install',
    'Instalar desde HoneyCheck-datos\\instaladores (params: file, args)',
  ],
  ['verify_program', 'Comprobar un programa instalado (name, min_version)'],
  ['verify_certificate', 'Comprobar un certificado personal (text)'],
  ['verify_service', 'Comprobar un servicio (name, state)'],
  ['verify_file', 'Comprobar que existe un archivo o carpeta (path)'],
  ['tool', 'Ejecutar una herramienta de soporte (tool, tool_params)'],
  ['command', 'Ejecutar un programa con ruta completa (command, exit_codes)'],
  ['manual', 'Paso que hace y marca el técnico'],
  ['reboot', 'Reiniciar: lo confirma el técnico'],
]

const runColumns: readonly Column<ProcedureRun>[] = [
  { key: 'name', label: 'Proceso', sortable: true, value: (run) => run.name },
  {
    key: 'progress',
    label: 'Avance',
    value: (run) =>
      `${String(run.steps.filter((s) => s.state === 'ok' || s.state === 'skipped').length)} de ${String(run.steps.length)}`,
  },
  {
    key: 'state',
    label: 'Estado',
    render: (run) =>
      run.finished ? (
        <Tag tone="ok">Terminado</Tag>
      ) : run.steps.some((s) => s.state === 'failed') ? (
        <Tag tone="bad">Con un paso fallido</Tag>
      ) : (
        <Tag tone="honey">Pendiente</Tag>
      ),
  },
  {
    key: 'updated',
    label: 'Última actividad',
    priority: 2,
    sortable: true,
    value: (run) => run.updatedAt,
    render: (run) => formatDate(run.updatedAt),
  },
  {
    key: 'device',
    label: 'Equipo',
    priority: 3,
    value: (run) => run.device ?? '',
  },
  {
    key: 'continue',
    label: 'Acción',
    render: (run) =>
      run.finished ? null : (
        <LinkButton
          size="small"
          href={toolHref('procedure.run', { run: run.id })}
        >
          Continuar
        </LinkButton>
      ),
  },
]

function ProcedureCard({
  procedure,
  onEdit,
  onRemove,
}: {
  procedure: Procedure
  onEdit: () => void
  onRemove: () => void
}) {
  return (
    <li className={styles.card} data-procedure={procedure.slug}>
      <div className={styles.head}>
        <h3>{procedure.name}</h3>
        {procedure.template ? (
          <Tag>Plantilla incluida</Tag>
        ) : (
          <Tag tone="honey">Versión {procedure.version}</Tag>
        )}
      </div>
      {procedure.description ? (
        <p className={styles.description}>{procedure.description}</p>
      ) : null}
      <details>
        <summary>{procedure.steps.length} pasos</summary>
        <ol className={styles.steps}>
          {procedure.steps.map((step) => (
            <li key={step.id}>
              {step.title}
              {step.optional ? (
                <span className={styles.muted}> (opcional)</span>
              ) : null}
            </li>
          ))}
        </ol>
      </details>
      <Toolbar align="center">
        <LinkButton
          tone="primary"
          size="small"
          href={toolHref('procedure.run', { procedure: procedure.slug })}
        >
          Ejecutar
        </LinkButton>
        <Button size="small" onClick={onEdit}>
          {procedure.template ? 'Personalizar' : 'Editar'}
        </Button>
        {procedure.template ? null : (
          <Button size="small" tone="ghost" onClick={onRemove}>
            Eliminar
          </Button>
        )}
      </Toolbar>
    </li>
  )
}

export function ProceduresPage() {
  const view = useProcedures()

  return (
    <>
      <h1>Procesos de instalación</h1>
      <Lede>
        Listas de pasos para dejar un equipo listo. Honey Check hace los pasos
        automáticos, se detiene en los manuales hasta que usted los marque y se
        puede continuar después, incluso tras reiniciar. Los instaladores se
        toman de HoneyCheck-datos\instaladores.
      </Lede>
      {view.message ? (
        <Notice>
          <p>{view.message}</p>
        </Notice>
      ) : null}

      {view.editing !== null ? (
        <section className={styles.editor} aria-labelledby="editor-title">
          <h2 id="editor-title">Editar proceso</h2>
          <p className={styles.muted}>
            Se guarda como versión nueva; las anteriores se conservan. Tipos de
            paso:
          </p>
          <dl className={styles.kinds}>
            {STEP_KINDS.map(([kind, label]) => (
              <div key={kind}>
                <dt>{kind}</dt>
                <dd>{label}</dd>
              </div>
            ))}
          </dl>
          <textarea
            className={styles.json}
            aria-label="Definición del proceso en JSON"
            spellCheck={false}
            rows={22}
            value={view.editing}
            onChange={(event) => {
              view.setEditing(event.target.value)
            }}
          />
          <Toolbar align="center">
            <Button tone="primary" onClick={() => void view.save()}>
              Guardar versión
            </Button>
            <Button
              tone="ghost"
              onClick={() => {
                view.setEditing(null)
              }}
            >
              Cancelar
            </Button>
          </Toolbar>
        </section>
      ) : (
        <Toolbar align="center">
          <Button onClick={view.create}>Nuevo proceso</Button>
        </Toolbar>
      )}

      <h2>Procesos</h2>
      {view.procedures === null ? (
        <Lede live>Cargando.</Lede>
      ) : (
        <ul className={styles.list}>
          {view.procedures.map((procedure) => (
            <ProcedureCard
              key={procedure.slug}
              procedure={procedure}
              onEdit={() => {
                view.edit(procedure)
              }}
              onRemove={() => {
                view.remove(procedure)
              }}
            />
          ))}
        </ul>
      )}

      <h2>Ejecuciones recientes</h2>
      <DataTable
        columns={runColumns}
        rows={view.runs ?? []}
        rowKey={(run) => run.id}
        loading={view.runs === null}
        emptyText="Todavía no se ejecutó ningún proceso."
      />
    </>
  )
}
