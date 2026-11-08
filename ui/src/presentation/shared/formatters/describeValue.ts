// Traduce los valores del contrato (con su confianza y motivo) a datos listos para mostrar.

import type { Confidence, Observed, PathEvidence } from '@/application'
import type { DisplayTag, DisplayValue, SpecRow } from '../types/display.types'
import { CONFIDENCE_TAGS, PATH_STATES, reasonText } from './labels'

function confidenceTag(confidence: Confidence): DisplayTag[] {
  const tag = CONFIDENCE_TAGS[confidence]
  return tag ? [{ label: tag[0], hint: tag[1] }] : []
}

export function describe<T>(
  observed: Observed<T> | null | undefined,
  format: (value: T) => string = String,
): DisplayValue {
  if (!observed || observed.value === null) {
    return {
      text: null,
      tags: [],
      source: observed?.source ?? null,
      reason: reasonText(observed?.reason) || null,
    }
  }
  return {
    text: format(observed.value),
    tags: confidenceTag(observed.confidence),
    source: observed.source,
    reason: null,
  }
}

/** Igual que `describe`, sin la insignia de confianza: para celdas de tabla. */
export function describeQuiet<T>(
  observed: Observed<T> | null | undefined,
  format?: (value: T) => string,
): DisplayValue {
  return { ...describe(observed, format), tags: [] }
}

export function describePath(
  path: PathEvidence | null | undefined,
): DisplayValue {
  if (!path?.value)
    return {
      text: null,
      tags: [],
      source: path?.source ?? null,
      reason: reasonText(path?.reason) || null,
      mono: true,
    }
  const state = PATH_STATES[path.state]
  const bad = path.state === 'missing' || path.state === 'inaccessible'
  const tags: DisplayTag[] = [
    ...(state
      ? [{ label: state, tone: bad ? ('bad' as const) : ('neutral' as const) }]
      : []),
    ...confidenceTag(path.confidence),
  ]
  return {
    text: path.value,
    tags,
    source: path.source,
    reason: null,
    mono: true,
  }
}

export function plain(
  text: string | null | undefined,
  mono = false,
): DisplayValue {
  return { text: text ?? null, tags: [], source: null, reason: null, mono }
}

export function spec<T>(
  label: string,
  observed: Observed<T> | null | undefined,
  format?: (value: T) => string,
): SpecRow {
  return { label, value: describe(observed, format) }
}

export function specText(
  label: string,
  text: string | null | undefined,
): SpecRow {
  return { label, value: plain(text) }
}
