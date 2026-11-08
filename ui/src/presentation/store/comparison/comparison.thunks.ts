import { createAppThunk } from '../createAppThunk'
import { comparisonActions } from './comparisonSlice'

/**
 * Preselección: «Comparar con» es la versión pedida (o el último análisis de este equipo) y la base,
 * la referencia de un equipo sano si existe.
 */
export const presetComparison = createAppThunk(
  'comparison/preset',
  async (requestedTargetId: string | null, { dispatch, getState, extra }) => {
    const state = getState()
    const targetId = requestedTargetId ?? state.inventory.history[0]?.id ?? null
    if (targetId)
      dispatch(
        comparisonActions.targetPicked(
          await extra.useCases.devices.versionOwner(targetId),
        ),
      )
    const referenceId = state.session.status?.referenceId ?? null
    if (referenceId && referenceId !== targetId) {
      dispatch(
        comparisonActions.basePicked(
          await extra.useCases.devices.versionOwner(referenceId),
        ),
      )
    }
  },
)

export const runComparison = createAppThunk(
  'comparison/run',
  async (_: undefined, { dispatch, getState, extra }) => {
    const { base, target } = getState().comparison
    if (!base || !target) return
    dispatch(comparisonActions.started())
    try {
      dispatch(
        comparisonActions.finished(
          await extra.useCases.comparison.compare(
            base.inventoryId,
            target.inventoryId,
          ),
        ),
      )
    } catch {
      dispatch(comparisonActions.finished(null))
    }
  },
)
