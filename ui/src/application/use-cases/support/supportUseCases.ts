// Herramientas de soporte: catálogo, plan, ejecución y procesos de instalación. Los rechazos del
// servicio se devuelven como resultado con motivo, no como excepción, porque la vista los explica.

import {
  GatewayError,
  type HoneyCheckGateway,
} from '../../ports/HoneyCheckGateway'
import type {
  SupportOutcome,
  SupportRefusal,
  SupportUseCases,
} from './support.types'

const KNOWN: Readonly<Record<string, SupportRefusal>> = {
  confirmation_required: 'confirmation_required',
  elevation_required: 'elevation_required',
  change_in_progress: 'change_in_progress',
  plan_expired: 'plan_expired',
  invalid_params: 'invalid_params',
  invalid_request: 'invalid_params',
  refused: 'refused',
  unknown_tool: 'not_found',
  procedure_not_found: 'not_found',
  run_not_found: 'not_found',
}

async function outcome<T>(work: () => Promise<T>): Promise<SupportOutcome<T>> {
  try {
    return { ok: true, value: await work() }
  } catch (error) {
    if (error instanceof GatewayError)
      return {
        ok: false,
        reason: (error.code ? KNOWN[error.code] : undefined) ?? 'failed',
        detail: error.reason,
      }
    throw error
  }
}

export function createSupportUseCases({
  gateway,
}: {
  gateway: HoneyCheckGateway
}): SupportUseCases {
  return {
    catalog: () => gateway.supportTools(),
    source: (name) => gateway.supportSource(name),
    plan: (tool, params) => outcome(() => gateway.supportPlan(tool, params)),
    start: (plan, confirmed) =>
      outcome(() => gateway.supportStart(plan.id, confirmed)),
    run: (runId) => gateway.supportRun(runId),
    cancel: (runId) => gateway.supportCancel(runId),
    history: () => gateway.supportHistory(),
    versions: (tool) => gateway.supportVersions(tool),
    changed: (runId) => gateway.supportChanged(runId),
    pickPath: (kind, title, filter) => gateway.pickPath(kind, title, filter),
    procedures: () => gateway.procedures(),
    procedureVersions: (slug) => gateway.procedureVersions(slug),
    saveProcedure: (document) => outcome(() => gateway.saveProcedure(document)),
    async removeProcedure(slug) {
      return (await gateway.deleteProcedure(slug)).removed
    },
    procedureRuns: () => gateway.procedureRuns(),
  }
}
