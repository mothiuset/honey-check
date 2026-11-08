// Ficha desplegable de un programa: dónde está, cómo se instaló y su firma.

import type { SoftwareItem } from '@/application'
import {
  INSTALLERS,
  SCOPES,
  SIGNATURES,
  describe,
  describePath,
  formatDay,
  plain,
  reasonText,
} from '@/presentation/shared/formatters'
import type { DisplayValue } from '@/presentation/shared/types'

export interface DetailEntry {
  readonly label: string
  readonly value: DisplayValue
  readonly wide?: boolean
}

function signatureText(item: SoftwareItem): string | null {
  const signature = item.executable?.signature
  if (!signature) return null
  const status = SIGNATURES[signature.status] ?? signature.status
  const signer = signature.signer ? `: ${signature.signer}` : ''
  const reason = signature.reason ? ` (${reasonText(signature.reason)})` : ''
  return `${status}${signer}${reason}`
}

export function programDetail(item: SoftwareItem): readonly DetailEntry[] {
  const entries: (DetailEntry | null)[] = [
    {
      label: 'Carpeta de instalación',
      value: describePath(item.installPath),
      wide: true,
    },
    {
      label: 'Ejecutable principal',
      value: describePath(item.executablePath),
      wide: true,
    },
    item.uninstall
      ? {
          label: 'Desinstalador (no se ejecuta)',
          value: plain(item.uninstall.command, true),
          wide: true,
        }
      : null,
    {
      label: 'Tipo de instalación',
      value: plain(INSTALLERS[item.installerType]),
    },
    { label: 'Instalado para', value: plain(SCOPES[item.scope]) },
    {
      label: 'Fecha de instalación',
      value: describe(item.installDate, formatDay),
    },
    item.executable
      ? {
          label: 'Versión del archivo',
          value: plain(item.executable.fileVersion),
        }
      : null,
    item.executable
      ? { label: 'Producto', value: plain(item.executable.productName) }
      : null,
    item.executable
      ? { label: 'Firma digital', value: plain(signatureText(item)) }
      : null,
    item.packageSignatureKind
      ? { label: 'Firma del paquete', value: plain(item.packageSignatureKind) }
      : null,
    {
      label: 'Detectado en',
      value: plain(item.detectionSource, true),
      wide: true,
    },
  ]
  return entries.filter((entry): entry is DetailEntry => entry !== null)
}
