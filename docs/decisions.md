# Decisiones técnicas

Vigentes salvo las marcadas **(reemplazada)**, que se conservan para saber por qué no se vuelve a ellas. Una decisión nueva o cambiada se escribe aquí en el mismo commit que el código.

## Python, Starlette y PyInstaller

**Decisión:** Python 3.12, Starlette/uvicorn, Pydantic y PyInstaller en modo carpeta. **Motivo:**
validación tipada y esquema JSON desde los modelos, y acceso a Registro y API nativas sin
dependencias compiladas propias. **Alternativas:** Go o .NET darían un ejecutable menor, pero
habría que construir a mano la validación y el esquema que Pydantic ofrece. **Coste:** una carpeta
de unos 25 MB (`HoneyCheck.exe` y `componentes\`); ver «Interfaz dentro del ejecutable».

## Starlette en lugar de FastAPI

FastAPI 0.162 incorpora un módulo de telemetría y exige `opentelemetry-api`, con exportadores que
pueden activarse desde variables de entorno. Sin el SDK no envía nada, pero el requisito es no llevar
telemetría, ni siquiera inactiva. La API local solo necesitaba rutas y validación, que Starlette y
Pydantic ya ofrecen. El empaquetado falla si entra un paquete de telemetría.

## Bandeja nativa en lugar de pystray

`pystray` es LGPLv3, y sus obligaciones de sustitución son difíciles de cumplir en un ejecutable
propietario de un solo archivo. Además arrastraba Pillow y `six`. `Shell_NotifyIcon` con `ctypes`
cubre lo necesario y también restaura el icono si el Explorador se reinicia. Coste: unas 300 líneas
propias de Win32, con pruebas reales. El empaquetado falla si entra una licencia copyleft.

## Ejecutable único en lugar de carpeta (reemplazada)

**Reemplazada** por «Interfaz dentro del ejecutable». El `.exe` único (`--onefile`) se
descomprimía en `%TEMP%` en cada arranque: lento, y los antivirus lo miran peor. No volver a él.

## WMI mediante subprocesos de PowerShell

**Decisión:** PowerShell 5.1 en subprocesos cortos, en lugar de COM dentro del proceso. **Motivo:**
un proveedor WMI colgado se puede matar de verdad; un hilo bloqueado en COM no. Falla por módulo sin
tumbar la aplicación. **Coste:** cerca de un segundo por lote y dependencia de PowerShell.

## Salida solo ASCII en PowerShell

Constrained Language no permite cambiar `[Console]::OutputEncoding` (comprobado). Se emite JSON con
escapes `\uXXXX`, de modo que el resultado no depende de la página de códigos.

## Eliminar `PSModulePath` de los subprocesos

Comprobado en este equipo: heredarlo de PowerShell 7 impide cargar los módulos de sistema de 5.1.

## Sin `-EncodedCommand`

Es la marca de muchos ataques y dispara detecciones de EDR. El comando queda en texto claro, auditable.

## Puerto 0 con socket propio

Evita la carrera de buscar un puerto libre y luego ocuparlo: uvicorn recibe el socket ya enlazado.

## Instancia única con mutex y evento

Sin archivos en el equipo: la segunda ejecución solo señala un evento y la primera abre su propia
interfaz. Ningún secreto pasa entre procesos. El sistema libera el mutex si el proceso muere.

## Renombrado sin reemplazo

`os.rename` en Windows falla si el destino existe y funciona en FAT32/exFAT, frecuentes en USB, donde
no hay enlaces duros. Así la escritura es atómica y nunca sobrescribe.

## Procedencia por valor

`Observed` impone que no exista un valor sin origen ni un desconocido sin motivo. Hace el JSON más
grande (630 KB en una prueba real con 236 programas), pero es el requisito central.

## Arquitectura por cabecera PE

Una primera versión deducía x86 de la vista WOW6432. Una auditoría con datos reales mostró productos
x64 clasificados como x86, porque instaladores de 32 bits los registran ahí. Solo la cabecera PE
verifica; lo demás es `probable`.

## Sin `Win32_Product`

Enumerarlo dispara verificaciones y reparaciones de todos los paquetes MSI.

## Interfaz sin framework (reemplazada)

**Reemplazada.** La primera interfaz eran tres archivos sin compilar. Hoy es React 18 con
TypeScript estricto, Redux Toolkit y CSS Modules, compilada con Vite y empaquetada dentro del
`.exe` ([arquitectura](architecture.md); diseño en `.agents/skills/honey-check-ui`). Siguen
vigentes la CSP estricta, nada de `innerHTML` y las fuentes del sistema (Bahnschrift, Segoe UI).

## Interfaz dentro del ejecutable

Un `.exe` único se descomprime en `%TEMP%` en cada arranque y los antivirus lo miran peor, así que
el programa sigue siendo una carpeta. Pero el técnico actualiza con frecuencia: el código y la
interfaz (1 MB) van dentro de `HoneyCheck.exe`, y `componentes\`, que casi nunca cambia, lleva una
huella. Actualizar es reemplazar un archivo de unos 6 MB. Una huella distinta se detiene con un
aviso en lugar de fallar a medias. La actualización la hace el técnico; la aplicación sigue sin
llamadas salientes.

## Una sola pantalla para cada cambio

La pantalla de «plan» y el diálogo «Sí, ejecutar» eran dos confirmaciones del mismo cambio y
ninguna decía lo concreto: qué existe, qué está en uso, qué necesita administrador. La revisión
previa lo dice en una frase y una lista, y su botón lleva el nombre de la acción: esa es la
confirmación. El plan sigue sellado por dentro; los comandos quedan plegados.

## Administrador por acción, no por sesión

Relanzar todo Honey Check como administrador perdía la pantalla en curso y obligaba a repetir los
pasos. Un proceso elevado de una sola acción, con el aviso UAC, conserva la sesión del técnico y
su contexto. Ver [seguridad](security.md#permisos).

## Explorador de espacio en lugar de ECharts

El mapa de bloques no se leía en modo oscuro, se quedaba en un bloque vacío al pasar el nivel que
traía el análisis y solo se podía usar con ratón. Una lista por nivel con barras proporcionales
(SVG) se lee, se usa con teclado y ofrece analizar aparte la carpeta donde el análisis no bajó
más. ECharts era la dependencia más pesada de la interfaz.

## Inventario cancelado no se guarda

Un análisis cancelado por el técnico no es un inventario. Un análisis con fallos sí se guarda, como
`partial`: tiene datos reales y declara lo que faltó.

## Solucionadores, no comandos sueltos

El técnico rechazó herramientas que solo envolvían un comando (`gpupdate`, reiniciar la cola, SFC):
tardan, no dicen qué estaba mal y muchas veces no lo arreglan. Una herramienta de soporte parte de
un problema («La impresora no imprime»): diagnostica en segundos con comprobaciones en paralelo,
arregla solo la causa encontrada y verifica que el síntoma desapareció; si no, dice qué sigue. Los
comandos sueltos quedan como herramientas ocultas (`hidden=True`) que los solucionadores enlazan.
Lo que este equipo no puede reproducir (dominio, impresora física, red caída) se prueba con un
Windows simulado (`tests/simulated_windows.py`) cuyo estado cambia cuando el arreglo funciona; eso
no cuenta como validación real ([pruebas](testing.md)).

## Versiones de cada consulta

Un análisis largo se perdía al cambiar de pantalla y había que repetirlo. Cada ejecución se guarda
comprimida en `HoneyCheck-datos\acciones`, con una línea de resumen en `indice.jsonl` para listar
versiones sin abrirlas. Al volver a una consulta se muestra lo que sigue en curso o su último
resultado, con sus versiones, «Actualizar» y qué cambió respecto de la anterior con los mismos
datos. Solo «Actualizar» la repite. Un cambio no se muestra de nuevo al volver: se revisa otra vez,
porque el equipo pudo cambiar desde entonces.

## Publicar desde el equipo del desarrollador

GitHub Actions en un repositorio privado consume minutos pagos, y no se van a pagar. `compilar.cmd`
compila para este equipo y deja solo la compilación nueva en `dist\HoneyCheck` (conserva
`HoneyCheck-datos`; una compilación a la vez y nada se toca con la app abierta, ver
[compilación](build.md)). `tools/publish.py` compila, prueba el `.exe` y reemplaza los archivos de la
versión `honey-check-latest`. El workflow queda solo para lanzarlo a mano. La descarga es la
última compilación **publicada**, no el último commit, y el README lo dice: el técnico usó varias
veces una descarga vieja creyéndola nueva.

## Número de compilación visible

Cada compilación lleva un número que siempre sube (`git rev-list --count HEAD`), el commit, la
fecha y si había cambios sin commit. La app lo muestra en el menú lateral y la página de descarga en
su título. La app no hace llamadas salientes, así que no puede saber si hay una más nueva: la
comparación la hace el técnico con esos dos números.

## Valores copiables y celdas de una línea

Seriales, IP, MAC, rutas y cifras se copian con un clic (`Copyable`); con texto seleccionado no
copia, así seleccionar sigue funcionando. Una celda de tabla ocupa una línea: lo largo se recorta
con «…» (las rutas por el principio, para ver el archivo) y se ve completo al pasar el puntero.
Las carpetas que administra Windows (`$RECYCLE.BIN`, `System Volume Information`, `Windows.old`)
dicen qué son y ofrecen solo su acción propia, en lugar de «Analizar» o «Abrir» que no llevan a
nada.

## Ejecutar donde está el técnico

Cada acción de un resultado era un enlace a la página de su herramienta: «Abrir en el Explorador»
llevaba a otra pantalla con un «Consultar». Ahora el botón decide por la herramienta
(`ActionButton`): lo **inmediato** (`instant=True`: abrir una carpeta, vaciar la caché DNS, una
página de prueba, exportar una clave) corre con el clic y un aviso dice cómo terminó; un **cambio**
abre su revisión en un panel lateral sobre la pantalla actual, su botón es la confirmación y el
resultado queda en el mismo panel (cerrarlo no detiene nada: sigue como aviso); solo una **consulta**
con resultado propio, o algo a lo que le faltan datos, abre su pantalla, donde empieza sola. Una
herramienta inmediata nunca borra ni pide administrador (`test_policy.py`). Tras un cambio, el
resultado de la pantalla avisa que quedó atrás y ofrece «Actualizar».

El Explorador se abría detrás de las demás ventanas: Windows no deja que un proceso en segundo plano
(el servicio) ponga una ventana al frente. Se busca la ventana que se abrió y se trae al frente
uniendo la entrada con la ventana activa (`shell.bring_explorer_forward`).

## Un periférico es un aparato físico

Windows parte un aparato en muchos nodos: un teclado con mouse y teclas multimedia aparecía como
nueve filas y el técnico creía que eran aparatos que no existen. El inventario lee el árbol de
dispositivos de `cfgmgr32` (incluidos los no presentes) y lo agrupa en el dominio, sin llamadas al
sistema (`domain/peripherals.group_devices`): por el contenedor que Windows asigna a cada aparato y,
para lo integrado, por el nodo padre. Nombre: el que reporta el propio aparato si el de Windows es
genérico. Lo no conectado se separa en emparejados por Bluetooth (quitarlos los desempareja: se
ofrece «Olvidar») y restos (se quitan con respaldo de sus controladores de terceros y se pueden
restaurar; Windows los vuelve a crear al reconectarlos). Las herramientas trabajan sobre el árbol
en vivo, no sobre el inventario, y nunca quitan algo conectado. Si el árbol no se puede leer, el
inventario vuelve a la lista de `Win32_PnPEntity`.

## Saber cuándo un resultado quedó atrás

«Programas por tamaño» leía el último inventario: un programa desinstalado seguía en la lista
aunque se actualizara. Ahora comprueba en vivo cuáles siguen instalados (Registro o carpeta del
paquete) y cuenta los instalados después del análisis. Además, una consulta puede declarar una
huella barata del estado que leyó (`SupportTool.state`: programas registrados, espacio libre con
1 GiB de tolerancia). Mientras su resultado está a la vista, la interfaz pregunta cada 8 s y al
volver a la ventana si cambió (`GET /api/support/runs/<id>/changed`), aunque el cambio se haya hecho
fuera de Honey Check, y ofrece «Actualizar».

## Almacenamiento: resumen aquí, detalle en Espacio en disco

La vista mostraba «Sin letra» en todas las unidades (por COM, `DriveLetter` llega como número: 67
es «C») y excluía los discos USB. Ahora cada unidad lleva su letra, su nombre, su uso y dos
acciones: **Abrir** (inmediata) y **Analizar espacio**, que lleva a Soporte > Espacio en disco. Esta
vista es el resumen; aquella dice qué ocupa cada carpeta. Los discos USB, tarjetas y FireWire van
en `storage.external` (sin guardar su serial: no son parte del equipo); `excluded` queda para los
virtuales y de red. Si Windows no da el fabricante se deduce del modelo, y si tampoco, se muestra
la marca de la controladora (`controllerVendor`, por su VEN_ PCI).

## Una sola tabla

`DataTable` es la única tabla de la interfaz (la comparación de versiones también la usa, con
`rowState`, `hideHeader` y `rowHeaders`). Tiene su propio desplazamiento: alto máximo según la
ventana, encabezado fijo y la barra horizontal siempre a la vista; cada celda en una línea, con
«…» si no cabe. Las barras de desplazamiento son de 6 px, sin carril, y se oscurecen al pasar el
puntero. `MetricCard` y `Notice` perdieron el borde lateral grueso: línea fina y tipografía.

## Controladores sin depender del texto de pnputil

`pnputil` escribe en el idioma de Windows: interpretar su texto se rompe en un equipo en inglés o
en español. Los paquetes de terceros se leen de `%SystemRoot%\INF\oem*.inf` (Windows guarda ahí
una copia de cada uno) con un lector de INF propio (`domain/drivers.py`): proveedor, versión,
fecha e identificadores de hardware de las secciones de modelos de x64. Los aparatos y sus
identificadores salen del árbol de dispositivos. Instalar desde una carpeta cruza cada `.inf` con
los aparatos de este equipo e instala solo lo que les sirve; después verifica que los que no
tenían controlador ya funcionan. `pnputil` solo se usa para actuar (agregar, exportar, quitar,
volver a buscar aparatos), por su código de salida.

## Elegir rutas con el diálogo de Windows

Una página no puede abrir el selector de carpetas de Windows ni conocer la ruta completa. El
servicio corre en el mismo equipo: `POST /api/pick` abre el diálogo nativo (carpeta o archivo)
con el navegador como dueño, lo trae al frente y devuelve la ruta elegida. Un parámetro con
`browse` («folder» o «file» y su filtro) muestra «Elegir…» junto a su campo; la marca la
interpreta la presentación (`formatters/browse.ts`), el dominio de la interfaz no la modela.

