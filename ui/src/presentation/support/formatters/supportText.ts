// Textos del soporte: por qué no se pudo, estados de ejecución y riesgo, y celdas de resultado.

import type {
  CellValue,
  CheckStatus,
  ColumnKind,
  Risk,
  RunStatus,
  SupportRefusal,
  Tone,
} from '@/application'
import type { TagTone } from '@/presentation/shared/components'
import {
  formatBytes,
  formatDate,
  formatNumber,
} from '@/presentation/shared/formatters'

export const REFUSALS: Readonly<Record<SupportRefusal, string>> = {
  confirmation_required: 'Este cambio necesita su confirmación.',
  elevation_required:
    'Esta acción necesita administrador y Windows no pudo pedirlo. Use «Ejecutar como administrador» en la barra inferior.',
  change_in_progress:
    'Ya hay un cambio en curso. Espere a que termine o cancélelo desde el historial.',
  plan_expired:
    'La revisión venció o ya se usó. Revise de nuevo para ver el estado actual.',
  invalid_params: 'Revise los datos del formulario.',
  refused: 'Honey Check no hace esta acción.',
  not_found: 'No se encontró lo pedido.',
  failed: 'El servicio no pudo preparar la herramienta.',
}

export const RISKS: Readonly<
  Record<Risk, { readonly label: string; readonly tone: TagTone }>
> = {
  read: { label: 'Solo consulta', tone: 'ok' },
  change: { label: 'Cambia el equipo', tone: 'honey' },
  destructive: { label: 'Elimina o desinstala', tone: 'bad' },
}

export const RUN_STATES: Readonly<
  Record<RunStatus, { readonly label: string; readonly tone: TagTone }>
> = {
  running: { label: 'En curso', tone: 'honey' },
  succeeded: { label: 'Terminado', tone: 'ok' },
  partial: { label: 'Terminado con avisos', tone: 'honey' },
  failed: { label: 'Falló', tone: 'bad' },
  cancelled: { label: 'Cancelado', tone: 'neutral' },
}

export const CHECK_MARKS: Readonly<
  Record<CheckStatus, { readonly mark: string; readonly label: string }>
> = {
  ok: { mark: '✓', label: 'Correcto' },
  warn: { mark: '!', label: 'Revisar' },
  fail: { mark: '✕', label: 'Falló' },
  info: { mark: 'i', label: 'Dato' },
  skipped: { mark: '–', label: 'Omitido' },
}

export const toneOf = (tone: Tone): TagTone =>
  tone === 'ok'
    ? 'ok'
    : tone === 'bad'
      ? 'bad'
      : tone === 'warn'
        ? 'honey'
        : 'neutral'

export function cellText(
  value: CellValue | undefined,
  kind: ColumnKind,
): string {
  if (value === null || value === undefined || value === '') return '—'
  if (kind === 'bytes' && typeof value === 'number') return formatBytes(value)
  if (kind === 'number' && typeof value === 'number') return formatNumber(value)
  if (kind === 'date' && typeof value === 'string') return formatDate(value)
  if (typeof value === 'boolean') return value ? 'Sí' : 'No'
  return String(value)
}

export function duration(startedAt: string, finishedAt: string | null): string {
  if (!finishedAt) return ''
  const seconds = Math.max(
    0,
    (Date.parse(finishedAt) - Date.parse(startedAt)) / 1000,
  )
  return seconds < 60
    ? `${seconds.toFixed(1)} s`
    : `${String(Math.floor(seconds / 60))} min ${String(Math.round(seconds % 60))} s`
}
