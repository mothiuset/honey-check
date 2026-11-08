// Formato de valores para la vista: configuración regional de Colombia y unidades explícitas.

const LOCALE = 'es-CO'
const BYTE_UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB'] as const

export function formatNumber(value: number, digits = 0): string {
  return value.toLocaleString(LOCALE, { maximumFractionDigits: digits })
}

export function formatBytes(bytes: number): string {
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1
  return `${formatNumber(value, digits)} ${BYTE_UNITS[unit] ?? 'B'}`
}

export function formatDate(iso: string, withTime = true): string {
  // Una fecha sola se interpreta como UTC y en América se mostraría el día anterior.
  const date = new Date(
    /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso,
  )
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(
    LOCALE,
    withTime
      ? { dateStyle: 'medium', timeStyle: 'short' }
      : { dateStyle: 'medium' },
  )
}

export const formatDay = (iso: string): string => formatDate(iso, false)
export const formatBool = (value: boolean): string => (value ? 'Sí' : 'No')
export const formatGhz = (mhz: number): string =>
  `${formatNumber(mhz / 1000, 2)} GHz`
export const formatMts = (value: number): string =>
  `${formatNumber(value)} MT/s`
export const formatPercent = (value: number): string =>
  `${formatNumber(value)} %`
export const formatMwh = (value: number): string => `${formatNumber(value)} mWh`
export const formatKib = (value: number): string => `${formatNumber(value)} KiB`

export function formatSpeed(bitsPerSecond: number): string {
  return bitsPerSecond >= 1e9
    ? `${formatNumber(bitsPerSecond / 1e9, 1)} Gb/s`
    : `${formatNumber(bitsPerSecond / 1e6)} Mb/s`
}

export function formatSeconds(milliseconds: number): string {
  return `${formatNumber(milliseconds / 1000, 1)} s`
}

// Texto sin tildes ni mayúsculas, para búsquedas locales.
export function fold(text: string | null | undefined): string {
  if (!text) return ''
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase()
}
