# Seguridad y permisos

## Lo que Honey Check hace en el equipo

| Acción | Detalle |
| --- | --- |
| Lee | WMI/CIM, Registro (`KEY_READ`), cabeceras y versión de ejecutables, manifiestos de paquetes |
| Ejecuta | Para el inventario, WMI por COM y `powershell.exe` de System32 solo con scripts de lectura. Para el soporte, herramientas de System32 (`sc`, `reg`, `certutil`, `msiexec`, `ipconfig`, `w32tm`, `DISM`…) con ruta completa y argumentos como lista, nunca a través de un shell |
| Escribe | `HoneyCheck-datos\` junto al ejecutable (inventarios, iconos, `logs\`), o en la carpeta que el técnico elija |
| Mueve | Lo que el técnico elimina desde la interfaz va a `HoneyCheck-datos\papelera\`, con su ruta original; nada se borra del disco |
| No escribe en el equipo | Corre desde su carpeta (sin extraerse en `%TEMP%`); logs, relevo de elevación y
perfil del navegador viven en `HoneyCheck-datos` |
| Escucha | `127.0.0.1` en un puerto que asigna Windows |

El análisis no cambia nada del equipo. Los cambios solo ocurren desde **Soporte**, una herramienta
a la vez y con las reglas de la sección siguiente. Nunca modifica GPO ni claves de directivas,
antivirus, AppLocker, WDAC ni integridad de memoria; no borra registros del sistema; no lee
contraseñas guardadas; no envía nada a internet ni incluye telemetría.

`tests/unit/test_policy.py` comprueba sobre el código que el inventario no usa ninguna API ni
comando de escritura, que nada en el producto usa `Win32_Product`, `-EncodedCommand`,
`Invoke-Expression`, `shell=True` ni herramientas de directivas, antivirus o AppLocker, que no hay
clientes de red salientes y que la interfaz no carga recursos externos.

## Herramientas de soporte

Cada herramienta declara su riesgo (consulta, cambio o destructiva) y si requiere administrador.

1. **Revisión previa.** Antes de pedir confirmación, la herramienta revisa lo concreto: qué existe,
   qué programa lo tiene en uso (Restart Manager de Windows) y qué necesita administrador. Lo dice
   en una frase y en una lista corta. Los pasos, con el comando equivalente que el técnico podría
   escribir a mano, quedan en «Ver comandos». Todo se sella con un hash de su contenido y se usa
   una sola vez: lo que se confirma es exactamente lo que se hace.
2. **Confirmación.** Un cambio o una acción destructiva se rechaza sin confirmación explícita. Si
   la revisión dice que hace falta administrador, Windows lo pide al ejecutar (ver
   [Permisos](#permisos)); Honey Check no se reinicia.
3. **Respaldo.** Las claves del Registro se exportan a `.reg`, los certificados a `.cer` y los
   servicios eliminados a `.reg` en `HoneyCheck-datos\respaldos`. Los archivos van a la Papelera de
   reciclaje. Las contraseñas no se pueden respaldar y el plan lo advierte.
4. **Alternativas.** Cada paso prueba una vía y, si falla, la siguiente: API de Windows, luego el
   comando del sistema, luego WMI o PowerShell. El registro de la ejecución dice cuál funcionó.
   Eliminar insiste en este orden: Papelera; cerrar lo que lo usa y reintentar; recuperar los
   permisos (con respaldo de las ACL en `.acl`) y reintentar; en modo forzado, borrar sin Papelera;
   y si algo de Windows lo sigue reteniendo, dejarlo programado para el próximo reinicio.
   Cerrar un programa usa primero el aviso de cierre de Windows y, si no responde, lo termina tras
   comprobar que el PID sigue siendo el mismo proceso (hora de inicio). Los procesos críticos nunca
   se terminan.
5. **Errores con sentido.** Un código de Windows nunca se muestra solo: se traduce a qué pasó y qué
   hacer, y el código queda en «Detalles técnicos». Los códigos de `SHFileOperation` (por ejemplo
   `0x78`, acceso denegado) se distinguen de los de Win32 con el mismo número.
6. **Verificación. Al terminar se comprueba el efecto: la clave ya no existe, el servicio quedó
   en el estado pedido, el programa ya no está registrado o la directiva se aplicó.
7. **Registro.** Cada ejecución queda en `HoneyCheck-datos\acciones` con sus parámetros, comandos,
   salida y resultado, comprimida (`.json.gz`); `indice.jsonl` guarda el resumen de cada una para
   listar versiones sin abrirlas. Los parámetros secretos (contraseña de un `.pfx`) se usan y se descartan:
   no llegan al plan, al registro ni a la interfaz.

Solo un cambio a la vez. Las consultas pueden correr en paralelo y todas se pueden cancelar.

Límites que ninguna herramienta cruza:

- Claves de directivas (`...\Policies\...`) en cualquier colmena: se leen, pero nunca se
  escriben ni se borran. Tampoco las claves raíz del sistema (`HKLM\SYSTEM`, `SAM`, `SECURITY`…).
- `Registry.pol` nunca se escribe. La única excepción es un archivo dañado (cabecera distinta de
  `PReg` versión 1, o el evento 1096 de Windows): «Las directivas no se aplican» lo copia a
  `respaldos` y lo renombra para que Windows lo genere de nuevo desde el dominio.
  `test_policy.py` lo exige.
- Carpetas del sistema (Windows, Program Files, la raíz del disco, el perfil completo) no se
  envían a la Papelera.
- Los instaladores de un proceso solo se toman de `HoneyCheck-datos\instaladores`.
- SNMP hacia impresoras y las consultas al controlador de dominio solo van a la dirección que el
  técnico indica o al dominio del equipo.

## Datos de ejecución

Todo lo que Honey Check genera queda en su carpeta de datos (`HoneyCheck-datos`), normalmente en la
USB: inventarios, iconos, logs, el relevo de la elevación y el perfil de la ventana de Edge. La
interfaz se abre en una ventana de Edge con ese perfil para que la sesión, que contiene datos del
equipo, no se mezcle con el perfil personal del usuario; Honey Check la cierra al salir. Si la
carpeta no permite escribir, los logs quedan solo en memoria.

Windows sí registra por su cuenta la ejecución de cualquier programa (Prefetch, Amcache, registros
de eventos si hay auditoría, historial del antivirus) y el historial de iconos de la bandeja.
Honey Check no modifica ni borra esos registros del sistema.

## Permisos

Arranca con los permisos del usuario: su manifiesto no pide elevación.

**Una acción de soporte que necesita administrador** corre en un proceso aparte: Honey Check lanza
`HoneyCheck.exe --support-worker` con el aviso de Control de cuentas, y la instancia del técnico
sigue sin elevar.

- La instancia abre una tubería con nombre aleatorio y le pasa al proceso elevado su nombre y una
  clave de 256 bits. Los dos lados se autentican con un desafío HMAC (`multiprocessing.connection`)
  y se hablan con JSON, nunca con pickle.
- El proceso elevado vuelve a validar los parámetros contra la definición de la herramienta,
  ejecuta solo esa, reenvía registro y avance en vivo, atiende la cancelación y termina. Si la
  instancia del técnico desaparece, se cancela solo.
- Los parámetros secretos viajan por la tubería: no tocan el disco ni la línea de comandos.
- Con credenciales de otro administrador en el aviso, el proceso elevado es otro usuario. Por eso
  viajan el SID y las carpetas del usuario de la sesión: `HKCU` se resuelve como `HKU\<SID>` y
  AppData y el Escritorio son los del técnico, no los del administrador.
- Si el aviso se cancela, la acción termina como cancelada y no cambia nada.

**Ejecutar como administrador** (barra de estado) relanza todo Honey Check con el aviso de Control
de cuentas, para el inventario completo (TPM, BitLocker):

- Windows pide las credenciales en su propio diálogo; Honey Check nunca las ve ni las guarda.
- La instancia actual cede su turno de instancia única, espera la entrada de la nueva y abre el
  navegador sin elevar. Si el aviso se cancela, todo sigue como estaba.
- La sesión elevada dura hasta cerrar Honey Check; al volver a abrirlo se arranca sin elevar.
- `test_policy.py` solo admite `runas`/`ShellExecute` en `elevation.py`, y solo para lanzar el
  propio ejecutable.

Sin administrador, lo siguiente queda como desconocido con motivo `access_denied`:

| Dato | Con usuario estándar |
| --- | --- |
| TPM | Presencia y versión sí (`Tbsi_GetDeviceInfo`); fabricante y estado no |
| BitLocker | No disponible |
| Batería | Depende del firmware |
| Software de otros usuarios | Solo se lee el usuario actual |

## Controles corporativos

Honey Check no intenta eludir AppLocker, WDAC ni Constrained Language:

- No usa `-EncodedCommand`, `-ExecutionPolicy` ni rutas alternativas de PowerShell.
- WMI se consulta por COM sin PowerShell; si una consulta falla por COM se repite por PowerShell,
  y si PowerShell está bloqueado se informa en lugar de buscar otra ruta.
- Los scripts funcionan en Constrained Language y el modo activo se reporta en la sección de seguridad.

## Consultas y datos no confiables

Las consultas son constantes del código, validadas con listas de caracteres permitidos. Las rutas
del Registro llegan a PowerShell como JSON por stdin: no pueden convertirse en código. Los comandos
de desinstalación se analizan como texto y **nunca se ejecutan**. Los manifiestos XML con DTD o
entidades se rechazan, y las lecturas tienen tamaño máximo. Las rutas de red no se tocan.

## API local

Escuchar en `127.0.0.1` no basta: cualquier página abierta en el navegador puede intentar llamar
a localhost.

| Amenaza | Control |
| --- | --- |
| Puerto ocupado o carrera | Puerto 0 asignado al crear el socket; `SO_EXCLUSIVEADDRUSE` |
| DNS rebinding | `Host` debe ser exactamente `127.0.0.1:<puerto>` |
| Peticiones desde otra web | `Origin` y `Sec-Fetch-Site` validados; sin CORS |
| CSRF | `SameSite=Strict`, token en cabecera y `Origin` obligatorio en cambios de estado |
| Robo del enlace de entrada | Ticket de un solo uso que caduca en 120 s; luego cookie `HttpOnly` |
| XSS desde nombres de programas | `textContent` en toda la interfaz y CSP sin `unsafe-inline` |
| Clickjacking | `frame-ancestors 'none'` |
| Lectura arbitraria de archivos | Identificadores validados y buscados en la lista de inventarios; recursos estáticos en lista cerrada |
| Ejecución de comandos | La API no acepta comandos ni consultas |
| Otro proceso en ese puerto | El navegador se abre tras comprobar el identificador de esta instancia |

La exportación alternativa solo acepta una carpeta local existente con escritura comprobada; el
nombre del archivo lo decide Honey Check.

**Riesgo residual:** otro programa del mismo usuario puede leer los mismos archivos, inspeccionar
procesos o conectarse al puerto, aunque sin cookie no accede a la API. El límite de confianza es la
sesión del usuario de Windows.

## Datos sensibles

Inventarios y logs se tratan como sensibles. Los logs registran módulos, duraciones y tipos de
error, sin seriales ni contenido del inventario, y sustituyen el perfil de usuario y el nombre del
equipo. Los mensajes de excepción de un módulo no llegan al JSON. Los temporales de escritura se
eliminan aunque esta falle. Los archivos **no van cifrados**: su protección depende de dónde se
guarden.
