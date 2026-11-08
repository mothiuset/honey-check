// Comparación de dos versiones, del mismo equipo o contra la referencia de un equipo sano.

import type { Comparison } from '@/domain/comparison/Comparison'
import type { HoneyCheckGateway } from '../../ports/HoneyCheckGateway'

export interface ComparisonUseCases {
  compare(baseId: string, targetId: string): Promise<Comparison>
}

export function createComparisonUseCases({
  gateway,
}: {
  gateway: HoneyCheckGateway
}): ComparisonUseCases {
  return { compare: (baseId, targetId) => gateway.compare(baseId, targetId) }
}
