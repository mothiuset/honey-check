# Manual del técnico

## Hacer un inventario

1. Conecte la USB y abra `HoneyCheck.exe`. El navegador se abre solo y aparece un icono de tarro
   en la bandeja del sistema, junto al reloj.
2. Pulse **Analizar equipo**. Cada celda del panal es una parte del inventario y se llena al
   terminar. Suele tardar menos de un minuto; la parte de software es la más lenta.
3. Al terminar verá el nombre del equipo y dónde quedó el archivo.
4. Salga con **Salir de Honey Check** o desde la bandeja, y expulse la USB de forma segura.

Cerrar la pestaña del navegador no cierra el programa. Para volver a entrar, haga doble clic en
el icono de la bandeja o abra de nuevo `HoneyCheck.exe`.

## Leer el panal

| Celda | Significado |
| --- | --- |
| Miel sólida | Completo |
| Miel rayada, con «parcial» | Se leyó, pero faltan algunos datos |
| Roja, con «falló» o «sin respuesta» | No se obtuvieron datos de esa parte |
| Punteada, con «cancelado» | Se canceló antes de terminar |

Un inventario parcial sigue siendo válido: en el panel, **Qué no se pudo leer** indica qué faltó.
Haga clic en una celda para ver sus datos.

## Leer los datos

| Marca | Significado |
| --- | --- |
| Sin etiqueta | Lo informó Windows, SMBIOS o el Registro |
| `verificado` | Comprobado contra el propio archivo |
| `calculado` | Obtenido con una regla fija a partir de datos de Windows |
| `probable` | Candidato deducido: puede no ser correcto |
| *Sin dato* | No se pudo determinar; al lado aparece el motivo |

Pase el puntero sobre un valor para ver de dónde salió.

## Menú de la bandeja

Clic derecho en el icono: **Abrir Honey Check**, **Analizar equipo**, **Abrir la carpeta de
inventarios**, **Estado del servicio** y **Salir de Honey Check**.

## Si algo falla

**La carpeta no permite escribir o se retiró la USB.** El inventario queda en memoria y aparece un
aviso. En **Exportaciones**, escriba una carpeta local y pulse **Guardar en esta carpeta**, o use
**Descargar con el navegador**. No cierre el programa antes: lo que está en memoria se perdería.

**Muchas celdas en rojo.** Lo más probable es que una directiva bloquee WMI o PowerShell. Los
programas del Registro se siguen listando. Honey Check no intenta saltarse el bloqueo: consulte con el
administrador del dominio.

**Datos marcados como «requiere más permisos».** TPM y BitLocker dan más detalle si un
administrador ejecuta el programa. Solo hágalo si necesita ese dato y está autorizado.

**El programa no abre.** Windows puede bloquearlo por no estar firmado (SmartScreen, AppLocker o
WDAC). No desactive esas protecciones: pida autorización a quien administra el equipo.

**Nada ocurre al abrirlo por segunda vez.** Ya estaba abierto: se abrirá la misma ventana. Solo
puede haber una instancia por sesión de usuario.

**Otro problema.** Revise `logs\honey-check.log` junto al ejecutable. No incluye seriales ni el
contenido del inventario, y sustituye su perfil de usuario y el nombre del equipo.

## Controladores

En **Soporte > Herramientas > Controladores** (y desde Hardware > Dispositivos con errores):

- **Controladores que faltan**: los aparatos conectados sin controlador o con error. Si Windows ya
  tiene uno que le sirve, **Reparar** lo reinstala; si no, dice el identificador del aparato para
  buscar su controlador.
- **Instalar controladores desde una carpeta**: **Elegir…** abre el diálogo de Windows; Honey Check
  lee cada `.inf` (también en subcarpetas), lo cruza con los aparatos de este equipo e instala solo
  los que sirven. La revisión dice cuántos sirven y para qué aparato; al final verifica que los que
  no tenían controlador ya funcionan.
- **Controladores instalados**: los de terceros con los aparatos que los usan; por fila
  **Respaldar**, **Reparar** y **Quitar** (con respaldo y **Reinstalar**). **Respaldar todos** antes
  de formatear.

## Periféricos

Cada aparato aparece una vez, con lo que hace debajo («teclado, mouse, teclas multimedia»); su
flecha muestra las partes que Windows registra. **No conectados** separa:

- **Emparejados por Bluetooth**: apagados o lejos. **Olvidar** los desempareja; para usarlos otra
  vez hay que emparejarlos de nuevo.
- **Ya no están**: se conectaron alguna vez. **Quitar** (uno o todos) respalda sus controladores en
  `HoneyCheck-datos\respaldos` y los quita; nunca quita lo conectado. «conectado ahora en otro
  puerto» marca el mismo aparato usado desde otra entrada USB. El resultado ofrece **Restaurar**.

## Soporte

1. Abra **Soporte > Herramientas** y elija una. También se llega desde el inventario: una impresora
   ofrece consultar su serial o imprimir una prueba; un programa de este equipo, desinstalarlo o
   buscar sus restos.
2. Una consulta se ejecuta al pulsar **Consultar**. Un cambio primero se revisa: una frase dice qué
   va a pasar y, debajo, cada elemento con su estado (si existe, qué programa lo tiene abierto, si
   hace falta administrador). Si llegó desde un enlace (un programa, una selección de restos), la
   revisión ya está hecha. El botón lleva el nombre de la acción: púlselo y empieza. Cambiar una
   opción, como el modo de desinstalación, vuelve a revisar sola. Los pasos con el comando que
   usted podría escribir están en **Ver los pasos y comandos**.
3. Mientras corre verá qué está haciendo y puede **Cancelar**. Al terminar, una frase dice cuánto se
   logró; cada elemento dice qué pasó y, si algo falló, por qué y qué hacer. El código de Windows
   queda en **Detalles técnicos**. Las tablas tienen búsqueda y botones por fila; algunas permiten
   elegir varias filas y aplicar una acción a todas. Un clic sobre un valor (serial, IP, MAC, ruta,
   cifra) lo copia; arrastrar sigue seleccionando el texto. Lo que no cabe en una celda se recorta
   con «…» y se ve entero al pasar el puntero.
4. Las acciones de una fila o de un resultado se ejecutan sin salir de la pantalla: lo inmediato
   (abrir una carpeta, vaciar la caché DNS) corre con el clic y un aviso abajo a la derecha dice
   cómo terminó; un cambio abre su revisión en un panel a la derecha, con un solo botón. Cerrar
   el panel no detiene lo que corre. Después de un cambio, el resultado de atrás avisa que hubo
   cambios y ofrece **Actualizar**.
5. Una consulta no se pierde al cambiar de pantalla: al volver a la herramienta se ve lo que sigue
   en curso o el último resultado, con su fecha. **Actualizar** la repite con los mismos datos;
   **Versiones** abre cualquiera de las anteriores, y debajo del resultado **Cambios desde…** dice
   qué cifras cambiaron y qué carpetas crecieron o bajaron respecto de la versión anterior.
4. Si la acción necesita administrador, Windows lo pide al empezar, solo para esa acción: Honey Check
   no se reinicia y el resultado vuelve a la misma pantalla. Si cierra el aviso, no cambia nada.
   Puede escribir las credenciales de otro administrador: el Registro y las carpetas siguen siendo
   los de la sesión abierta.

**Desinstalar.** El modo normal usa el desinstalador del programa sin preguntas y después muestra
los restos para elegir cuáles eliminar. **Con el asistente** abre el del programa. **Forzado** lo
quita de raíz aunque el desinstalador falle o no exista: cierra el programa, detiene sus servicios,
intenta el desinstalador con límite de tiempo, quita su registro de Windows Installer y elimina
carpetas, accesos directos, Registro, inicio automático, servicios, tareas programadas y reglas del
firewall, con respaldo de cada cosa.

**Analizar espacio.** Cada disco físico aparece con su modelo, su tipo (NVMe, SATA, USB; SSD o HDD)
y sus particiones, cada una con su espacio libre. Marque las que quiera (de discos distintos se
recorren a la vez) o escriba una carpeta. Las particiones que Windows reserva (EFI, recuperación)
se muestran pero no se analizan. **Volver a leer** muestra una USB recién conectada.

**Sin red o sin internet.** La revisión recorre las capas en orden: adaptador, dirección IP,
router, DNS, salida a internet y proxy. La primera que falla es la causa; las de arriba dicen
«Depende de la capa anterior», así nunca se culpa al DNS de un cable desconectado. **Corregir la
conexión** hace solo lo que esa causa pide (habilitar o reiniciar el adaptador, renovar la IP,
vaciar la caché DNS) y vuelve a comprobar todo. Si el problema está en el router, el proveedor o
un firewall de la red, lo dice y no toca el equipo.

**La impresora no imprime.** Elija la impresora en la lista (la predeterminada primero). La revisión
dice si el servicio de impresión corre, si la impresora está marcada «sin conexión» o en pausa, qué
informa ella misma (papel, tóner, atasco, puerta), si responde en la red y si hay trabajos trabados.
**Corregir la impresora** arregla lo que depende del equipo, quita solo los trabajos trabados (no
los de otras impresoras) y, al final, imprime una página de prueba si la dejó marcada.

**Windows Update no actualiza.** La revisión muestra servicios, directivas de la empresa (por
ejemplo un servidor WSUS o el acceso bloqueado al usuario, que Honey Check nunca cambia), conexión,
reinicio pendiente, espacio libre y el último error traducido. **Corregir Windows Update** arregla
lo encontrado y busca actualizaciones de verdad para comprobarlo; si la búsqueda falla, su código
indica el arreglo siguiente (caché, almacén de componentes) y se vuelve a buscar. Los errores de
aplicaciones de la Tienda se muestran aparte: no son de Windows Update.

**Windows dañado.** Primero revisa en segundos el almacén de componentes; DISM corre solo si está
dañado. Después SFC revisa los archivos del sistema; el avance se ve en vivo, porque puede tardar
de 10 a 15 minutos. El resultado dice cuántos archivos reparó y cuáles no pudo; si quedó alguno,
repara el almacén y pasa SFC otra vez. Si hay un reinicio pendiente, pide reiniciar antes de
empezar, porque Windows no repara en ese estado.

**Las directivas no se aplican.** Al abrirla ya está el diagnóstico: controlador, puertos, hora,
canal seguro, SYSVOL, `Registry.pol`, errores de directivas y su servicio, cada uno con su estado.
Si la causa se puede corregir desde el equipo, el botón **Corregir y aplicar directivas** corrige
solo eso, aplica y verifica. Si no (sin red al controlador, puertos bloqueados), el botón queda
bloqueado y la lista dice qué revisar.

**Eliminar insiste.** Si la Papelera no puede, Honey Check cierra lo que usa la carpeta (primero con
el aviso de cierre de Windows; si no responde, termina el proceso), recupera los permisos guardando
antes los originales en un `.acl`, y si algo de Windows la sigue reteniendo, la deja programada para
el próximo reinicio. El resultado dice cuál de esas vías funcionó.

Cada ejecución queda en **Soporte > Historial**. Los respaldos (`.reg`, `.cer`, `.acl`, `.xml`) están en
`HoneyCheck-datos\respaldos`; lo enviado a la Papelera se recupera desde la Papelera de Windows.

## Procesos de instalación

En **Soporte > Procesos de instalación** hay tres plantillas: equipo recién formateado, oficina y
firma digital. **Personalizar** abre la definición en JSON; al guardarla queda como versión nueva y
las anteriores se conservan.

- Copie los instaladores a `HoneyCheck-datos\instaladores` (la ruta del paso es relativa a esa
  carpeta). Un `.msi` se instala en silencio con `msiexec`; un `.exe` con los argumentos del paso.
- **Ejecutar** hace los pasos automáticos y se detiene en el primer paso manual o reinicio. Marque
  el paso como hecho en la tabla y pulse **Continuar el proceso**.
- Un paso obligatorio que falla detiene el proceso; corrija la causa y use **Reintentar lo que
  falló**. Un paso opcional que falla queda omitido con su motivo.
- Las ejecuciones pendientes aparecen abajo con **Continuar**, aunque haya reiniciado el equipo.

## Tratamiento de los archivos

Los inventarios contienen seriales, nombres de equipo, direcciones MAC e IP y rutas que pueden
incluir nombres de usuario. Trátelos como información institucional. Honey Check no los envía a
ningún lugar; compartirlos es decisión de usted.

## Comparar dos análisis

En **Historial**, elija dos inventarios y pulse **Comparar**. Verá los cambios de hardware y
sistema, y los programas nuevos, retirados y actualizados.
