import type { Plan } from '@/application'
import { Button } from '@/presentation/shared/components'
import { useCopy } from '../../hooks/useCopy'
import { CheckList } from '../CheckList/CheckList'
import { StatusGlyph } from '../StatusGlyph/StatusGlyph'
import styles from './ConfirmPanel.module.css'

interface ConfirmPanelProps {
  readonly plan: Plan
  readonly isElevated: boolean
  readonly onStart: () => void
  readonly onEdit: (() => void) | null
}

/**
 * Lo que va a pasar, antes de hacerlo: una frase, la revisión previa de cada elemento y un solo
 * botón. Los pasos con su comando equivalente quedan plegados para quien quiera verlos.
 */
export function ConfirmPanel({
  plan,
  isElevated,
  onStart,
  onEdit,
}: ConfirmPanelProps) {
  const { copied, copy } = useCopy()
  const blocked = plan.checks.some((check) => check.status === 'fail')
  const asksAdmin = plan.requiresAdmin && !isElevated
  return (
    <section className={styles.panel} aria-labelledby="confirm-summary">
      <p id="confirm-summary" className={styles.summary}>
        {plan.summary ?? `Se ejecutará «${plan.title}».`}
      </p>

      {plan.checks.length ? <CheckList checks={plan.checks} /> : null}

      {plan.warnings.length ? (
        <ul className={styles.notes}>
          {plan.warnings.map((warning) => (
            <li key={warning}>
              <StatusGlyph status="warn" />
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className={styles.actions}>
        <Button
          tone={plan.risk === 'destructive' ? 'danger' : 'primary'}
          onClick={onStart}
          disabled={blocked}
        >
          {plan.actionLabel ?? plan.title}
        </Button>
        {onEdit ? (
          <Button tone="ghost" onClick={onEdit}>
            Cambiar los datos
          </Button>
        ) : null}
        <span className={styles.hint} role="status">
          {blocked
            ? 'Resuelva lo marcado en rojo antes de empezar.'
            : asksAdmin
              ? 'Windows pedirá permiso de administrador solo para esta acción.'
              : null}
        </span>
      </div>

      {plan.backup ? (
        <p className={styles.backup}>Respaldo: {plan.backup}</p>
      ) : null}

      <details className={styles.commands}>
        <summary>Ver los pasos y comandos ({plan.steps.length})</summary>
        <ol>
          {plan.steps.map((step, index) => (
            <li key={`${String(index)}-${step.title}`}>
              <span>{step.title}</span>
              {step.detail ? (
                <span className={styles.detail}>{step.detail}</span>
              ) : null}
              {step.command ? (
                <span className={styles.command}>
                  <code>{step.command}</code>
                  <Button
                    size="small"
                    tone="ghost"
                    onClick={() => {
                      copy(step.command ?? '')
                    }}
                    aria-label={`Copiar el comando del paso ${String(index + 1)}`}
                  >
                    {copied === step.command ? 'Copiado' : 'Copiar'}
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </details>
    </section>
  )
}
