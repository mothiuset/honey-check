import { useEffect } from 'react'
import type { DeviceVersion } from '@/application'
import { useRoute } from '@/presentation/shared/navigation'
import {
  comparisonActions,
  presetComparison,
  runComparison,
  selectComparison,
  selectComparisonAreas,
  selectComparisonTotals,
  selectFilteredSoftware,
  useAppDispatch,
  useAppSelector,
  type ComparisonFilter,
} from '@/presentation/store'

/** Comparación de dos versiones: selección, filtro y resultado agrupado por área. */
export function useComparison() {
  const dispatch = useAppDispatch()
  const { params } = useRoute()
  const requested = params.get('target')
  const { base, target, result, loading, filter } =
    useAppSelector(selectComparison)

  useEffect(() => {
    void dispatch(presetComparison(requested))
  }, [dispatch, requested])

  return {
    base,
    target,
    result,
    loading,
    filter,
    ready: Boolean(base && target),
    areas: useAppSelector(selectComparisonAreas),
    software: useAppSelector(selectFilteredSoftware),
    totals: useAppSelector(selectComparisonTotals),
    pickBase: (value: DeviceVersion | null) =>
      dispatch(comparisonActions.basePicked(value)),
    pickTarget: (value: DeviceVersion | null) =>
      dispatch(comparisonActions.targetPicked(value)),
    setFilter: (value: ComparisonFilter) =>
      dispatch(comparisonActions.filtered(value)),
    run: () => void dispatch(runComparison()),
  }
}
