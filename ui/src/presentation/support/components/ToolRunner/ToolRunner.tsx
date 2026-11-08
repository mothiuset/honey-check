import type { ToolDefinition } from '@/application'
import {
  Button,
  Lede,
  Notice,
  Tag,
  Toolbar,
} from '@/presentation/shared/components'
import { useOpenFolder } from '@/presentation/shared/hooks/useOpenFolder'
import { RouteLink } from '@/presentation/shared/navigation'
import { SUPPORT_VIEW } from '../../formatters/supportRoutes'
import { REFUSALS, RISKS } from '../../formatters/supportText'
import { useToolRunner } from '../../hooks/useToolRunner'
import { ConfirmPanel } from '../ConfirmPanel/ConfirmPanel'
import { ResultView } from '../ResultView/ResultView'
import { RunView } from '../RunView/RunView'
import { ToolForm } from '../ToolForm/ToolForm'
import { Changes } from '../Changes/Changes'
import { Verdict } from '../Verdict/Verdict'
import { VersionBar } from '../VersionBar/VersionBar'
import styles from './ToolRunner.module.css'

interface ToolRunnerProps {
  readonly tool: ToolDefinition
  readonly given: Readonly<Record<string, string>>
  readonly auto: boolean
}

/**
 * Una herramienta en una sola pantalla: los datos, lo que va a pasar con un botón para hacerlo,
 * y después qué se logró. Un cambio que llega desde un enlace ya viene revisado.
 */
export function ToolRunner({ tool, given, auto }: ToolRunnerProps) {
  const runner = useToolRunner(tool, given, auto)
  const openFolder = useOpenFolder()
  const { plan, run, notice } = runner
  const running = run?.status === 'running'
  const isRead = tool.risk === 'read'
  const risk = RISKS[tool.risk]
  const editable = tool.params.some(
    (param) => param.kind !== 'multi' && !runner.fixed.has(param.name),
  )
  // Un cambio deja el formulario a la vista junto a su revisión: cambiar el modo la actualiza.
  const showForm = !running && (isRead || (!run && (editable || !plan)))

  return (
    <>
      <RouteLink className={styles.back} href={`#${SUPPORT_VIEW}`}>
        Volver a Soporte
      </RouteLink>
      <h1>{tool.title}</h1>
      <Lede>{tool.description}</Lede>
      <p className={styles.tags}>
        <Tag tone={risk.tone}>{risk.label}</Tag>
        {tool.contactsNetwork ? (
          <Tag>Consulta otro equipo de la red</Tag>
        ) : null}
      </p>

      {showForm ? (
        <ToolForm
          tool={tool}
          values={runner.values}
          missing={runner.missing}
          busy={runner.preparing}
          onChange={runner.setValue}
          onSubmit={runner.submit}
          fixed={runner.fixed}
          showSubmit={isRead || !plan}
        />
      ) : null}

      {runner.preparing && !isRead ? (
        <Lede live>Revisando el equipo antes de empezar…</Lede>
      ) : null}

      {notice ? (
        <Notice tone="bad">
          <p>
            {REFUSALS[notice.reason]}
            {notice.detail ? ` (${notice.detail})` : ''}
          </p>
        </Notice>
      ) : null}

      {plan && !isRead && !run ? (
        <ConfirmPanel
          plan={plan}
          isElevated={runner.isElevated}
          onStart={runner.start}
          onEdit={null}
        />
      ) : null}

      {run && isRead ? (
        <VersionBar
          run={run}
          versions={runner.versions}
          onOpen={runner.openVersion}
          onRefresh={runner.refresh}
          busy={runner.preparing}
          stale={runner.stale}
        />
      ) : null}
      {run ? <Verdict run={run} /> : null}
      {run?.result ? (
        <ResultView result={run.result} onOpenFolder={openFolder} />
      ) : null}
      {run && runner.previous ? (
        <Changes before={runner.previous} after={run} />
      ) : null}
      {run ? <RunView run={run} onCancel={runner.cancel} /> : null}
      {/* Si algo no se logró, revisar de nuevo muestra el estado actual y lo que falta. */}
      {run && !running && !isRead && run.status !== 'succeeded' ? (
        <Toolbar>
          <Button onClick={runner.reset}>Revisar de nuevo</Button>
        </Toolbar>
      ) : null}
    </>
  )
}
