import type { ScanProgress } from '@/application'

/** Una línea con el avance o el resultado del análisis. */
export function scanLine(
  scan: ScanProgress | null,
  message: string | null,
): string {
  if (!scan) return ''
  if (scan.state === 'running')
    return `Analizando: ${String(scan.completed)} de ${String(scan.total)} módulos terminados.`
  if (scan.state === 'cancelling') return 'Cancelando el análisis.'
  if (scan.state === 'cancelled' || scan.state === 'failed')
    return scan.detail ?? ''
  return message ?? ''
}
