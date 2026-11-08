// Textos que la sesión muestra al técnico.

export const SESSION_MESSAGES = {
  sessionLost:
    'Esta pestaña perdió la sesión. Abra Honey Check desde el icono de la bandeja.',
  startFailed:
    'No se pudo cargar Honey Check. Cierre esta pestaña y ábralo desde la bandeja.',
  serviceStopped: 'Honey Check se cerró. Ya puede cerrar esta pestaña.',
  scanAlreadyRunning: 'Ya hay un análisis en curso.',
  scanFailed: 'No se pudo iniciar el análisis.',
  confirmElevation: 'Confirme el aviso de Control de cuentas de Windows.',
  elevationCancelled:
    'Se canceló el aviso de administrador. Honey Check sigue con los permisos actuales.',
  elevationFailed: 'No se pudo iniciar Honey Check como administrador.',
  restartingElevated:
    'Honey Check se reinicia como administrador y abrirá una pestaña nueva. Ya puede cerrar esta.',
} as const
