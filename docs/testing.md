# Pruebas y compatibilidad

Este documento separa lo simulado de lo ejecutado de verdad. **Que una marca aparezca en las
pruebas con mocks no significa que Honey Check se haya probado en un equipo de esa marca.**

## Tipos de prueba

| Tipo | Ruta | Qué es real | Qué es simulado |
| --- | --- | --- | --- |
| Unitarias con mocks | `tests/unit` | Reglas y módulos | Respuestas de WMI, Registro y archivos |
| Integración con mocks | `tests/integration` | Coordinador, API con seguridad, JSON en disco | Respuestas del sistema |
| Windows real | `tests/windows` | PowerShell, WMI, Registro, sockets, mutex, bandeja | Algunos datos de análisis en las pruebas de servidor |
| Navegador real | `tests/e2e` | Edge o Chrome, servidor HTTP | Análisis con datos ficticios |
| Empaquetado | `tests/packaging` | El `.exe` construido, en caja negra, contra el Windows del equipo | Nada |

## Cobertura de los escenarios

| Escenario | Dónde | Tipo |
| --- | --- | --- |
| Acer, HP, Lenovo, Dell y pcSmart | `test_hardware_collectors` | Mock |
| Relleno de SMBIOS en equipos ensamblados | `test_hardware_collectors` | Mock |
| DDR4 y DDR5, uno o varios módulos; sin deducir por frecuencia | `test_hardware_collectors` | Mock |
| Discos SATA y NVMe; HDD; incierto | `test_hardware_collectors`, `test_domain` | Mock |
| Exclusión de USB aunque figure como fijo | `test_hardware_collectors` | Mock |
| Windows 10 y 11, ediciones y LTSC | `test_system_collectors` | Mock |
| Aplicaciones x86 y x64 | `test_software_collector` | Mock |
| Sin `InstallLocation`; rutas incorrectas; por usuario | `test_software_collector` | Mock |
| Versión y ruta de ejecutables reales | `test_real_adapters` | Real |
| Firma real; ruta hostil tratada como dato | `test_real_adapters` | Real |
| Constrained Language (simulado dentro de la sesión) | `test_real_adapters` | Real |
| Errores de WMI y permisos insuficientes | `test_*_collectors`, `test_scan_and_store` | Mock |
| Clase y espacio de nombres inexistentes; acceso denegado | `test_real_adapters` | Real |
| Puertos ocupados; apertura y cierre del servidor | `test_server_real` | Real |
| Recuperación tras un fallo de arranque | `test_server_real` | Fallo simulado, socket real |
| Instancia única | `test_lifecycle_real`, `test_executable` | Real |
| Bandeja con sus cinco opciones | `test_tray_real` | Real; opciones elegidas con el mensaje de Windows |
| Desaparición del directorio | `test_lifecycle_real`, `test_usb_removal` | Real, con unidad `subst` |
| Exportación JSON válida; sin sobrescribir | `test_scan_and_store`, `test_executable` | Mock y real |
| Escritura interrumpida | `test_scan_and_store` | Fallo simulado, disco real |
| Datos parciales y recuperación | `test_scan_and_store`, `test_usb_removal` | Mock y real |
| Tiempos límite y cancelación | `test_scan_and_store`, `test_real_adapters` | Mock y real |
| Seguridad de endpoints | `test_http_security`, `test_server_real` | Aplicación real |
| XSS con nombres de programa | `test_ui` | Navegador real |
| Salida limpia y temporales eliminados | `test_executable` | Real |
| Ruta con espacios y acentos | `test_executable` | Real |
| Motor de soporte: confirmación, administrador, plan de un uso, un cambio a la vez, secretos | `test_support_engine` | Mock |
| Acción como administrador en otro proceso: tubería autenticada, registro en vivo sin secretos, cancelación, aviso rechazado | `test_elevated_worker` | Tubería real; el proceso elevado es un hilo (el aviso UAC no se automatiza) |
| Quién usa un archivo y cerrarlo (Restart Manager, terminar consola); Program Files pide administrador | `test_removal_real` | Real, con un proceso que deja abierto un archivo de la prueba |
| Códigos de Windows traducidos, GUID comprimido de MSI, HKCU de otro usuario | `test_support_programs` | Puro |
| Discos con sus particiones; varias unidades analizadas y combinadas | `test_support_volumes`, `test_real_adapters` | Discos simulados; lectura real del disco del sistema |
| Escenarios de punta a punta con Windows simulado: dominio (hora, Registry.pol, canal seguro, tickets, controlador inalcanzable, puertos, error 1058) red (cable, Wi-Fi deshabilitado, APIPA, DHCP mudo, router, caché DNS, servidor DNS caído, sin salida, proxy) impresora (servicio detenido, sin conexión, pausa, trabajos trabados que se quitan o no, atasco, sin red, no instalada) Windows Update (servicio deshabilitado o por directiva, caché, almacén de componentes descubierto al buscar, código desconocido, sin conexión, poco espacio, errores de la Tienda, WSUS) y Windows dañado (sano, almacén dañado, archivos reparados, no reparables con segunda pasada, DISM sin origen, reinicio pendiente, CBS.log rotado, avance en vivo) | `test_scenarios_*`, `test_support_ui` | Simulación (`tests/simulated_windows.py`) que cambia de estado cuando un arreglo surte efecto |
| Directivas: causas (hora, Registry.pol, 1096, canal seguro), bloqueo sin controlador o puertos, respaldo y renombre de Registry.pol | `test_support_policies` | Dominio simulado; Registry.pol en una carpeta temporal |
| API de soporte con sesión, CSRF y códigos de error | `test_support_api` | Aplicación real, herramientas ficticias |
| Procesos: versiones, espera del técnico, reanudar, reintento explícito | `test_support_parts` | Disco real |
| SNMP: codificación y decodificación de respuestas | `test_support_parts` | Paquetes construidos en la prueba |
| Recorrido de carpetas sin seguir uniones | `test_support_parts` | Real, con unión creada por la prueba |
| Herramientas de lectura de soporte en este equipo | `test_support_real` | Real |
| Registro: escribir, exportar, borrar con respaldo; rechazo de directivas | `test_support_real` | Real, sobre una clave de HKCU creada por la prueba |
| Credencial: listar sin secreto y eliminar | `test_support_real` | Real, sobre una credencial ficticia creada por la prueba |
| Proceso con pasos automáticos y manual | `test_support_real` | Real |

## Dónde se ejecutó de verdad

| Entorno | Qué se ejecutó | Resultado |
| --- | --- | --- |
| Windows 11 IoT Enterprise LTSC 24H2, x64, portátil, usuario estándar | Todas las pruebas y el `.exe` con bandeja y navegador | Correcto |
| GitHub Actions `windows-2022` (Windows Server) | Pruebas y `.exe` | Solo si se lanza a mano: no corre en cada push desde 2026-11-07 |
| GitHub Actions `windows-2025` (Windows Server) | Pruebas y el `.exe` construido en `windows-2022` | Solo si se lanza a mano: no corre en cada push desde 2026-11-07 |

## Validaciones pendientes

Sin evidencia todavía, por falta de equipos. Son necesarias antes de declarar estable una versión:

- [ ] Windows 10, cualquier edición, incluida LTSC
- [ ] Equipo real Acer
- [ ] Equipo real HP
- [ ] Equipo real Lenovo
- [ ] Equipo real Dell
- [ ] Equipo real pcSmart o ensamblado
- [ ] Memoria DDR5 real
- [ ] Disco SATA y HDD reales
- [ ] Disco USB externo real conectado al analizar
- [ ] Extracción física real de la USB durante la ejecución
- [ ] Equipo con dominio y directivas reales
- [ ] AppLocker o WDAC reales (Constrained Language solo se simuló)
- [ ] Antivirus corporativo real frente al ejecutable sin firmar
- [ ] Clic físico sobre el menú de la bandeja (se envió el mensaje de Windows, sin ratón)
- [ ] Ejecución como administrador: detalle de TPM y BitLocker
- [ ] «Ejecutar como administrador» real: aviso UAC aceptado y cancelado, relevo de la instancia y
      apertura del navegador sin elevar (las pruebas cubren la API con un relanzador simulado)
- [ ] Interfaz 0.3 en el equipo del técnico: navegación, comparación, papelera y barra de estado
- [ ] Soporte con administrador: directivas (`gpupdate`), hora, canal seguro, SFC, DISM, punto de
      restauración, reinicio de Windows Update y limpieza de componentes
- [ ] Desinstalación real de un programa y búsqueda de restos (MSI, instalador propio y Store)
- [ ] Desinstalación forzada real con el desinstalador roto o ausente
- [ ] Acción de soporte con aviso UAC real: aceptado, cancelado y con credenciales de otro
  administrador (HKCU y AppData del usuario de la sesión)
- [ ] Eliminar una carpeta de Program Files sin sesión elevada (el caso del código 120)
- [ ] «Windows dañado» con daño real (solo se probó la revisión en este equipo sano y la
  simulación de DISM, SFC y CBS.log)
- [ ] «La impresora no imprime» con una impresora física de red y USB (solo se probaron las
  virtuales de este equipo y la simulación)
- [ ] «Sin red o sin internet» real: cable desconectado, Wi-Fi deshabilitado y DHCP caído (en
  este equipo solo se ejecutó con la red funcionando)
- [ ] «Las directivas no se aplican» en un equipo de dominio real: hora desfasada, canal seguro
  roto, Registry.pol dañado y controlador inalcanzable (solo se probó en grupo de trabajo)
- [ ] Quitar Office real (Click-to-Run con ODT y sin ella; MSI)
- [ ] Impresora de red real: SNMP, página de prueba, agregar por IP y vaciar cola
- [ ] Certificados reales de token (Andes, Certicámara, GSE): listar, exportar e instalar raíz
- [ ] Procesos de instalación con instaladores reales en `HoneyCheck-datos\instaladores`
- [ ] Quitar restos de periféricos real (`pnputil /remove-device` y respaldo de un oem*.inf)
  y restaurarlos; solo se probó la agrupación y la lectura del árbol en este equipo y el
  quitado en la simulación
- [ ] «Olvidar» un aparato Bluetooth real (clásico y LE); solo se probó en la simulación
- [ ] Instalar controladores desde una carpeta en un equipo recién formateado (con aparatos sin
  controlador); se probó la lectura y el cruce en este equipo y la instalación en la simulación
- [ ] Quitar y reparar un controlador real (solo simulación)

Marque cada casilla solo con evidencia real, sin incluir datos del equipo en el repositorio.
