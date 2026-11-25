# Propuesta: diagnóstico y gestión de restricciones de Windows Update

**Estado:** propuesta para revisión; no implementada.  
**Fecha:** 25 de noviembre de 2026.  
**Área:** Soporte → Sistema → Windows Update no actualiza.

## Contexto y objetivo

En un caso real de soporte sobre Windows 11 unido a un dominio, Windows Update aparecía restringido aunque sus servicios principales estaban operativos. Los informes de políticas resultantes identificaron una GPO de dominio que impedía la interacción manual y las actualizaciones automáticas. Restablecer la caché o reinstalar componentes no solucionaría la causa administrativa. No se ha demostrado que dicha restricción fuera la causa de otros síntomas de inestabilidad del equipo.

Se propone ampliar el solucionador existente de Windows Update de Honey Check, no crear otro que duplique sus comprobaciones. El técnico debe poder detectar qué impide actualizar, conocer su procedencia, revisar acciones para habilitar o deshabilitar restricciones cuando corresponda, aplicar las correcciones autorizadas y verificar el resultado real, con respaldo y reversión.

El ejemplo está anonimizado: no se incorporan nombres de equipos, usuarios, dominios, GUID reales, direcciones ni informes de clientes.

## Restricción arquitectónica vigente

AGENTS.md y docs/security.md prohíben escribir claves de directivas, modificar GPO o Registry.pol (salvo la recuperación existente de un archivo comprobado como dañado). tests/unit/test_policy.py impone esos límites. Esta propuesta **no revoca esas decisiones** ni autoriza a eliminar sus pruebas.

La primera entrega debe funcionar dentro de esos límites: diagnóstico completo, acciones de reparación no relacionadas con políticas y guía de administración autorizada. Un editor de directivas locales sería una segunda entrega condicionada a una decisión explícita del proyecto que delimite la excepción, actualice la documentación y preserve las demás prohibiciones. Las políticas de dominio y MDM se administran en su plataforma de origen, fuera del ejecutable portable. No usar escrituras en el Registro como mecanismo para neutralizar una política efectiva de dominio o MDM.

## 1. Diagnóstico de restricciones

Recopilar en paralelo, con tiempo límite y cancelación, reutilizando el motor de soporte:

- Identidad de la sesión interactiva, SID, elevación, pertenencia a dominio, compilación y edición de Windows.
- Directivas efectivas de equipo y usuario mediante RSoP y/o gpresult (XML o salida estructurada cuando esté disponible). Registrar nombre de GPO ganadora, ámbito, origen, vínculo y fecha de aplicación únicamente cuando la evidencia lo permita.
- Registro de Windows Update en HKLM y HKU del usuario interactivo, incluyendo subclave AU; políticas MDM efectivas de Update, configuración de fuentes, WSUS y señales de conflictos GPO/MDM.
- Estado e inicio de wuauserv, BITS, CryptSvc, UsoSvc, DoSvc y WaaSMedicSvc. Un servicio de inicio bajo demanda detenido no constituye por sí solo una falla.
- Eventos WindowsUpdateClient y GroupPolicy; proxy WinHTTP, conectividad con el origen autorizado, espacio, reinicio pendiente y resultado de búsqueda mediante la API de Windows Update.
- Diferenciar las actualizaciones del sistema de los errores de Microsoft Store.

La elevación con otra cuenta no debe cambiar el usuario cuyos datos se diagnostican. Usar la resolución de sesión existente. Una lectura denegada, una consulta sin conectividad al dominio o una política de origen no demostrado se representan como desconocidas, no como ausencia de restricciones.

### Catálogo mínimo de políticas

| Valor | Interpretación contextual |
| --- | --- |
| SetDisableUXWUAccess | Restringe el acceso del usuario a las funciones de Windows Update. |
| DisableWindowsUpdateAccess | Restricción heredada; interpretar según ámbito y versión. |
| NoAutoUpdate | Deshabilita la actualización automática; no implica necesariamente que toda búsqueda manual esté bloqueada. |
| DoNotConnectToWindowsUpdateInternetLocations | Restringe conexiones públicas en escenarios aplicables; evaluar junto con la configuración de origen. |
| UseWUServer, WUServer, WUStatusServer | Configuración de WSUS; un servidor corporativo no es por sí mismo un fallo. |
| DisableDualScan | Directiva heredada, dependiente de la versión; no asumir que sigue siendo efectiva. |
| DeferFeatureUpdates, DeferFeatureUpdatesPeriodInDays | Aplazamiento de características, distinto de bloquear todas las actualizaciones. |
| ExcludeWUDriversInQualityUpdate | Exclusión de controladores en actualizaciones de calidad. |
| SetPolicyDrivenUpdateSourceFor*Updates, UseUpdateClassPolicySource | Selección del origen por clase: calidad, características, controladores y otras actualizaciones. |
| Pause*Updates*, TargetReleaseVersion, TargetReleaseVersionInfo, ProductVersion | Pausas y versión objetivo; evaluar vigencia, compatibilidad y alcance. |

Mantener un catálogo versionado con tipo, ámbito, ruta, estados válidos, aplicabilidad a la compilación, efecto, fuente oficial y recomendaciones. Diferenciar no configurada, habilitada, deshabilitada, no aplicable y desconocida; no confundir un DWORD en cero con una política no configurada. Los valores residuales del Registro no prueban por sí solos qué GPO los estableció.

## 2. Interfaz y acciones

Ampliar la pantalla existente según .agents/skills/honey-check-ui, con un resumen de salud, una tabla de restricciones y detalles técnicos expandibles. Mantener navegación y componentes existentes; no crear una interfaz paralela.

Cada fila mostrará nombre legible, valor efectivo, alcance, procedencia (local, dominio, MDM, residual o desconocida), impacto, evidencia, estado de administración y acción disponible. Filtros por origen, impacto y estado. Permitir seleccionar varias acciones compatibles y revisar un plan único.

| Acción | Comportamiento |
| --- | --- |
| Analizar / actualizar | Solo lectura; mostrar cambios respecto al último diagnóstico. |
| Habilitar acceso manual | Identificar qué restricciones concretas deben retirarse, sin alterar la programación de actualizaciones. |
| Habilitar actualizaciones automáticas | Revisar configuración de Automatic Updates y proponer una configuración conforme a la estrategia autorizada. |
| Permitir controladores | Revisar la exclusión y el origen de actualizaciones de drivers, sin instalar nada automáticamente. |
| Administrar origen de actualización | Mostrar WSUS, Windows Update o fuente administrada por clase; no reemplazar el origen corporativo por defecto. |
| Activar / desactivar / dejar no configurada una directiva | Mostrar opciones válidas y sus consecuencias; ejecución local únicamente si existe una excepción de diseño aprobada y el origen local está demostrado. |
| Gestionar restricción de dominio o MDM | Mostrar evidencia y procedimiento de cambio en GPMC o la consola MDM; exportar una propuesta de excepción acotada al equipo para el administrador autorizado. |
| Reparar Windows Update | Reutilizar el solucionador existente únicamente si la evidencia indica un problema de servicio, caché o componentes; no usarlo para evadir políticas. |
| Verificar / revertir | Volver a consultar el estado efectivo, buscar actualizaciones con autorización y revertir solo los cambios propios admitidos por la herramienta. |

Ejemplo: si una GPO de dominio establece SetDisableUXWUAccess=1 y NoAutoUpdate=1, mostrar ambas restricciones y su GPO de origen. Ofrecer generar el plan para autorizar acceso manual o automático por separado. No excluir toda una GPO sin evaluar las demás configuraciones que contiene. La excepción de dominio debe conservar las directivas no relacionadas, limitarse al equipo autorizado y ser administrada por quien tiene permisos delegados. No incluir un botón para borrar masivamente las políticas de una OU.

Si el origen es local y la segunda entrega ha sido aprobada, el técnico podrá elegir los estados admitidos de las directivas del catálogo mediante mecanismos soportados de administración local. Si no existe esa aprobación, mostrar la guía para gestionarlas desde el editor de directivas de Windows y un botón para volver a verificar.

## 3. Plan, permisos, respaldo y reversión

- Diagnóstico por defecto sin elevación; elevar solo la acción que lo requiera mediante ElevatedExecutor y el diálogo de Windows.
- El plan sellado del motor debe incluir estado previo, objetivo, alcance, valores que se modificarían, permisos, efecto, riesgos y validación; nunca ejecutar comandos suministrados por la UI o leídos del Registro.
- Si se habilita en el futuro la edición local: catálogo cerrado de directivas, respaldo previo de estado y origen, comprobación de que no hay política administrada que gobierne el valor, y nueva lectura inmediatamente antes de aplicar. Ante ambigüedad, conflicto, cambio concurrente o respaldo fallido, detenerse sin escribir.
- La reversión restaura exactamente los estados previos de las acciones propias, incluido el estado no configurado; no importa una rama completa del Registro ni pisa cambios posteriores de otro administrador. Para GPO/MDM, el administrador revierte en su origen.
- No deshabilitar controles de seguridad, antivirus, AppLocker, WDAC, servicios de administración, ni usar tareas persistentes para contrarrestar gpupdate. Sin reinicios, descargas ni instalaciones de actualizaciones automáticas iniciadas por Honey Check.
- Historial de soporte en HoneyCheck-datos/acciones y respaldos en HoneyCheck-datos/respaldos. Registrar errores de arranque, UAC cancelado, acceso denegado, tiempos, acciones omitidas, resultados parciales y verificación. Si no hay escritura disponible, informar y no ejecutar cambios que requieren respaldo.
- Exportar un informe JSON y una vista legible; anonimizar explícitamente antes de compartir. No enviar datos fuera de la máquina.

## 4. Verificación funcional

Distinguir estos resultados: acceso manual permitido, actualización automática configurada, origen de búsqueda válido, búsqueda exitosa, actualizaciones disponibles, reinicio requerido, restricción aún aplicada, prueba no realizada y error de búsqueda.

Volver a leer políticas efectivas después del cambio autorizado o de la actualización normal de directivas; contrastar la interfaz de Windows Update y ejecutar la búsqueda por la API existente solo con autorización, usando el origen configurado. Una búsqueda puede generar tráfico al servicio de actualización configurado, aunque no descarga ni instala paquetes. Si el entorno está desconectado, reportar que no se pudo verificar. No marcar corregido solo porque un valor del Registro cambió o porque se abrió Configuración.

Si una GPO vuelve a aplicar la restricción, mostrarlo como política administrada vigente y no reintentar indefinidamente.

## 5. Integración técnica

Conservar Ports & Adapters y composición única. Revisar el solucionador actual y sus contratos antes de introducir clases nuevas.

| Capa | Propuesta |
| --- | --- |
| Domain | Modelo tipado de observación, origen, restricciones efectivas, aplicabilidad, plan y resultado de verificación; sin E/S. |
| Application | Orquestación de diagnóstico, clasificación, propuesta de cambios, verificación y comparación de resultados; puertos de lectura y acciones admitidas. |
| Infrastructure | Lectura de RSoP, Registro, eventos, servicios y API Windows Update; reutilizar adaptadores existentes y sus límites. Cualquier futura escritura local necesita aprobación arquitectónica previa. |
| Presentation | Ampliar el solucionador y sus tablas/acciones, progreso, cancelación y detalles técnicos, utilizando el gateway y motor existentes. |
| Persistencia | Historial local versionado de soporte, respaldo y exportación; inventario estrictamente de solo lectura. |

Usar consultas nativas cuando estén disponibles, alternativas de solo lectura soportadas por el proyecto, tiempos límite y cancelación real. No interpretar texto de gpresult dependiente del idioma como única evidencia; mantener pruebas ES/EN. Fallar rápido si faltan capacidades o permisos, no bloquear la interfaz ni repetir consultas idénticas innecesariamente.

## 6. Entregas propuestas

1. **Diagnóstico:** catálogo, identificación del origen, evidencias, tabla de restricciones, exportación e historial. Reutilizar el solucionador.
2. **Remediación asistida:** acciones de soporte existentes, planes granulares para directivas, guía de GPMC/MDM, actualización de resultados y verificación mediante búsqueda.
3. **Edición local opcional:** únicamente tras aprobación expresa de una decisión arquitectónica y de seguridad; mecanismos soportados, alcance cerrado, respaldo, confirmación y reversión. Sin edición de dominio o MDM desde Honey Check.

## 7. Pruebas y criterios de aceptación

- [ ] Detecta correctamente restricciones de acceso manual, actualizaciones automáticas, origen WSUS/WU, controladores y aplazamientos.
- [ ] Diferencia GPO local, dominio, MDM y origen desconocido; no atribuye una política por un valor aislado.
- [ ] Reproduce con fixtures ficticios el caso de servicios sanos y acceso restringido por una GPO de dominio.
- [ ] No recomienda limpiar la caché ni reparar componentes cuando el bloqueo administrativo es la única causa demostrada.
- [ ] Funciona con usuario estándar, elevación con otra cuenta, UAC cancelado, dominio desconectado y PowerShell restringido.
- [ ] Mantiene intactas las políticas administradas; no ofrece acciones ejecutables que contradigan AGENTS.md.
- [ ] Si se aprueba la edición local, prueba estados habilitado/deshabilitado/no configurado, idempotencia, respaldo, reversión, cambios concurrentes y fallos parciales en equipos de laboratorio autorizados.
- [ ] Una búsqueda exitosa sin actualizaciones disponibles se diferencia de una búsqueda fallida o no realizada.
- [ ] Al volver a la pantalla, el resultado refleja las acciones aplicadas o advierte que está desactualizado.
- [ ] Las pruebas de seguridad siguen pasando y no contienen datos de equipos reales.
- [ ] Ejecutar las comprobaciones de README y documentar pruebas reales por separado de mocks conforme a docs/testing.md.

## Referencias de implementación

- [Arquitectura](docs/architecture.md), [Seguridad](docs/security.md), [Decisiones](docs/decisions.md) y [Roadmap](docs/roadmap.md).
- Microsoft Learn: [Administrar actualizaciones mediante directivas](https://learn.microsoft.com/windows/deployment/update/waas-wu-settings), [Policy CSP – Update](https://learn.microsoft.com/windows/client-management/mdm/policy-csp-update), [gpresult](https://learn.microsoft.com/windows-server/administration/windows-commands/gpresult), [Windows Update Agent API](https://learn.microsoft.com/windows/win32/wua_sdk/portal-client).

La funcionalidad propuesta no está implementada ni validada por este documento. Las referencias externas deben contrastarse con las versiones de Windows soportadas durante la implementación.
