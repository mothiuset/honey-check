import type { OperatingSystem, SecuritySection } from '@/application'
import {
  CODE_INTEGRITY,
  OS_GENERATIONS,
  VBS_STATES,
  formatBool,
  formatDate,
  spec,
} from '@/presentation/shared/formatters'
import type { SpecRow } from '@/presentation/shared/types'

const label = (map: Readonly<Record<string, string>>) => (value: string) =>
  map[value] ?? value

export function operatingSystemSpecs(os: OperatingSystem): readonly SpecRow[] {
  return [
    spec('Nombre', os.name),
    spec('Generación', os.generation, label(OS_GENERATIONS)),
    spec('Edición', os.editionId),
    spec('LTSC', os.isLtsc, formatBool),
    spec('Versión', os.displayVersion),
    spec('Compilación', os.fullBuild),
    spec('Arquitectura', os.architecture),
    spec('Instalado', os.installedAt, formatDate),
    spec('Último arranque', os.lastBootAt, formatDate),
    spec('Actualizaciones registradas', os.hotfixCount),
  ]
}

export function securitySpecs(security: SecuritySection): readonly SpecRow[] {
  return [
    spec('Arranque seguro', security.secureBootEnabled, formatBool),
    spec(
      'Seguridad basada en virtualización',
      security.virtualizationBasedSecurity,
      label(VBS_STATES),
    ),
    spec('Integridad de memoria', security.memoryIntegrityRunning, (running) =>
      running ? 'En ejecución' : 'Detenida',
    ),
    spec(
      'Directiva de integridad de código',
      security.codeIntegrityPolicy,
      label(CODE_INTEGRITY),
    ),
    spec('Control de cuentas (UAC)', security.uacEnabled, formatBool),
    spec('Modo de lenguaje de PowerShell', security.powershellLanguageMode),
  ]
}

export function defenderSpecs(
  defender: NonNullable<SecuritySection['defender']>,
): readonly SpecRow[] {
  return [
    spec('Antivirus habilitado', defender.antivirusEnabled, formatBool),
    spec('Protección en tiempo real', defender.realTimeProtection, formatBool),
    spec('Modo', defender.runningMode),
    spec('Firmas actualizadas', defender.signatureUpdatedAt, formatDate),
  ]
}
