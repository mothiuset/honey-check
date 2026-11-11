<p align="center"><img src="docs/assets/honey-check.svg" alt="Honey Check" width="480"></p>

# Honey Check 🍯

Aplicación portable para Windows que recopila el inventario técnico de un equipo, lo guarda
versionado por equipo en la carpeta `HoneyCheck-datos` junto al ejecutable, y reúne las
herramientas de soporte del día a día con revisión previa, respaldo y verificación. Funciona sin
instalación, sin internet y sin servidor externo. Arranca sin permisos de administrador y los pide
con el aviso de Windows solo si el técnico lo elige.

## ⬇️ Obtener Honey Check

### Qué versión tengo

Abajo en el menú lateral de la app, por ejemplo:

```text
Versión 0.2.0 · compilación 676 · 2a16530 · 2026-11-07
```

El **número de compilación siempre sube** (es la cantidad de commits de la rama): si el suyo es
menor que el de la última compilación, está desactualizado. Le siguen el commit y la fecha. Un clic
lo copia. «desarrollo» es el servidor de desarrollo, no un ejecutable; «con cambios sin commit»
es una compilación hecha con cambios locales que no están en ningún commit.

### En el PC del desarrollador: compilar (siempre lo último)

Doble clic en **`compilar.cmd`**, o desde una terminal en esa carpeta:

```powershell
.\compilar.cmd              # al terminar abre la carpeta
.\compilar.cmd --sin-abrir  # sin abrir el Explorador
```

- Deja en **`dist\HoneyCheck\`** solo la compilación nueva: la anterior
  se borra.
- **Conserva `HoneyCheck-datos`** (inventarios, respaldos, registros) si la app se usó desde esa
  carpeta.
- Si Honey Check está abierto desde esa carpeta, se detiene y pide cerrarlo: no lo cierra solo.
- Si la compilación falla, la carpeta anterior queda tal cual y el error se ve en la ventana.
- Al terminar dice el número de compilación y el commit: los mismos que mostrará la app.
- Necesita [uv](https://docs.astral.sh/uv/) y Node.js; la primera vez instala lo que falte. Tarda
  alrededor de un minuto.

Para llevarlo a una USB, copie la carpeta `HoneyCheck` completa (el `.exe` y `componentes\`).

### En otro PC: descargar la última compilación **publicada**

> [!IMPORTANT]
> La descarga **no** se actualiza sola con cada cambio: contiene la última compilación que se
> publicó con `tools/publish.py` (ver [compilación](docs/build.md#publicar-una-compilación)), que
> puede ir detrás de la rama. Antes de descargar, mire el **título de la
> [página de descarga](https://github.com/mothiuset/honey-check/releases/tag/honey-check-latest)**: dice la compilación, el commit y la fecha. La fecha que GitHub
> muestra junto al título es la de creación de la página, no la de los archivos.

1. Si las notas de la página dicen que **cambió `componentes`**, o es la primera vez:
   [HoneyCheck-experimental.zip](https://github.com/mothiuset/honey-check/releases/download/honey-check-latest/HoneyCheck-experimental.zip). Si no:
   [solo HoneyCheck.exe](https://github.com/mothiuset/honey-check/releases/download/honey-check-latest/HoneyCheck.exe), para reemplazarlo en su carpeta `HoneyCheck`.
2. Si ya tenía una descarga anterior en Descargas, el navegador guarda la nueva como
   `HoneyCheck-experimental (1).zip`: descomprima **esa** y reemplace la carpeta `HoneyCheck`
   completa; no mezcle archivos de dos compilaciones.
3. Abra `HoneyCheck.exe` y compare el número de compilación del menú lateral con el título de la
   página. Si no coincide, está abriendo otra copia.

El repositorio es privado: los enlaces funcionan con una cuenta de GitHub con acceso. Por terminal:

```powershell
gh release download honey-check-latest -R mothiuset/honey-check -p "HoneyCheck.exe*" --clobber
Get-FileHash .\HoneyCheck.exe -Algorithm SHA256   # igual a HoneyCheck.exe.sha256
```

No está firmado: SmartScreen puede advertirlo y AppLocker o WDAC pueden bloquearlo
([firma de código](docs/build.md#firma-de-código)).

Estado: **experimental**. Consulte [pruebas y compatibilidad](docs/testing.md) y
[limitaciones](docs/limitations.md) antes de confiar en él para un equipo o una marca concretos.
## Uso

1. Copie la carpeta `HoneyCheck` a una memoria USB y abra `HoneyCheck.exe` con doble clic.
2. Pulse **Analizar equipo** en la página que se abre.
3. El inventario queda en `HoneyCheck-datos\equipos\<equipo>\inventarios\`, como una versión
   nueva (`v0001_….json`, `v0002_….json`…); la barra de estado muestra la ruta completa.
4. Salga desde el icono de la bandeja o con el botón **Salir de Honey Check**.

[Manual del técnico](docs/technician-manual.md).

## Qué recopila

Identificación, procesador, memoria, almacenamiento interno, sistema operativo, gráficos,
pantallas, red, batería, TPM, dispositivos con errores, seguridad, impresoras (puerto, IP, driver,
estado y cola), periféricos conectados, uno por aparato físico con lo que hace (fabricante, modelo, serial, VID/PID, conexión), y los que Windows recuerda sin estar conectados (emparejados por Bluetooth y restos) y programas
instalados con versión, editor, carpeta, ejecutable, arquitectura y firma. Cada valor declara su origen y
confiabilidad; lo que no puede determinarse queda como desconocido, con su motivo.

El análisis solo lee. Los cambios ocurren únicamente desde Soporte, a pedido del técnico.

## Qué puede hacer en Soporte

Antes de un cambio, Honey Check revisa el equipo y dice en una frase qué va a pasar: qué existe,
qué programa lo tiene en uso y si hace falta administrador. Un botón lo hace. Lo que necesita
administrador pide permiso a Windows solo para esa acción, sin reiniciar Honey Check. Cada cambio
guarda respaldo, insiste por otra vía si la primera falla, verifica el resultado y explica cada
error en palabras del técnico (el código de Windows queda en «Detalles técnicos»).

| Área | Herramientas |
| --- | --- |
| Espacio en disco | Elegir unidades de cualquier disco físico (cada disco con sus particiones, su tipo y su espacio) o una carpeta, y recorrerlas a la vez; explorador del espacio nivel por nivel; archivos más grandes; tamaño real de cada programa; enviar a la Papelera; vaciar la Papelera de una unidad; `$RECYCLE.BIN`, `System Volume Information` y `Windows.old` dicen qué son; abrir en el Explorador |
| Limpieza | Vista previa por categoría (temporales, cachés de navegadores y Teams, Windows Update, optimización de entrega, volcados, Papelera); limpiar lo elegido; limpieza de componentes con DISM (admin) |
| Programas | Desinstalar con el desinstalador oficial, `msiexec` o Remove-AppxPackage y comprobar; modo forzado que lo quita de raíz aunque el desinstalador falle (cierra el programa, detiene sus servicios, limpia Windows Installer y todos los restos); buscar restos con evidencia (carpetas, accesos directos, Registro, inicio automático, servicios, tareas programadas, reglas del firewall) y eliminarlos insistiendo: cierra lo que los usa, recupera permisos y, si Windows los retiene, los deja para el reinicio; quitar Office por completo con la ODT o el cliente Click-to-Run (admin) |
| Impresoras | **La impresora no imprime**: elegir la impresora (predeterminada, de red, locales, virtuales) y revisar servicio de impresión, «sin conexión», pausa, lo que la impresora informa (papel, tóner, atasco, puerta), su puerto de red y los trabajos trabados; corrige lo que depende del equipo (iniciar el servicio, ponerla en línea, reanudar, quitar solo los trabajos trabados), comprueba e imprime una página de prueba (admin). Además: listar con puerto, IP y driver; serial, contador, MAC y consumibles por SNMP; agregar por IP (admin); drivers |
| Red | **Sin red o sin internet**: recorre en menos de un segundo adaptador, IP, router (por ARP, aunque filtre el ping), DNS (consulta directa a cada servidor), salida a internet y proxy; la primera capa que falla es la causa y se corrige solo esa (habilitar o reiniciar el adaptador, renovar IP, vaciar DNS) y se vuelve a comprobar; lo que depende del router o del proveedor se dice y no se intenta. Ping y probar un puerto como utilidades |
| Dominio y directivas | **Las directivas no se aplican**: diagnóstico en paralelo en segundos (controlador, puertos 88/389/445, hora, canal seguro, SYSVOL, cabecera de Registry.pol, errores de directivas del registro de eventos, servicio); corrige solo la causa (hora, canal seguro, tickets de Kerberos, Registry.pol dañado), aplica con límite de tiempo y verifica; si la causa no se arregla desde el equipo (red, firewall), lo dice y no lo intenta (admin) |
| Certificados | Listar con vencimiento, clave privada y token; exportar; instalar `.cer` o `.pfx`; eliminar con respaldo |
| Servicios y procesos | Servicios (iniciar, detener, reiniciar, tipo de inicio; admin); procesos (terminar); programas de inicio (activar o desactivar, reversible) |
| Sistema | Eventos recientes de error; SFC y DISM (admin); punto de restauración (admin); reiniciar Windows Update (admin); programar o cancelar un reinicio; informe de batería; **Windows Update no actualiza**: servicios (tipo de inicio desde el Registro), directivas de la empresa y WSUS (solo lectura), conexión, reinicio pendiente, espacio y el código de error traducido (los de aplicaciones de la Tienda se separan); corrige solo esa causa (habilitar servicios, renovar la caché, DISM) y verifica buscando actualizaciones con la API de Windows Update; si la búsqueda falla, su código decide el arreglo siguiente; **Windows dañado**: estado del almacén de componentes en segundos, DISM solo si está dañado, SFC con avance en vivo, lo que SFC reparó o no leído del CBS.log, y si SFC no pudo, DISM y segunda pasada (admin) |
| Registro | Navegar, buscar, exportar; crear o cambiar valores y eliminar claves o valores con respaldo `.reg`. Las claves de directivas y las del sistema no se modifican |
| Credenciales | Listar las del Administrador de credenciales sin mostrar contraseñas; eliminar una |
| Procesos de instalación | Plantillas (equipo recién formateado, oficina, firma digital) y procesos propios versionados: instalan desde `HoneyCheck-datos\instaladores`, comprueban programas, servicios y certificados, se detienen en los pasos manuales y se continúan después |

Todo queda en **Historial** y en `HoneyCheck-datos\acciones` (comprimido, con un índice de versiones: al volver a una consulta se ve su último resultado, se actualiza y se compara con la anterior); los respaldos en `respaldos`.

## Documentación

| Documento | Contenido |
| --- | --- |
| [Manual del técnico](docs/technician-manual.md) | Uso diario y solución de problemas |
| [Arquitectura](docs/architecture.md) | Capas, flujo y cómo añadir un módulo |
| [Contrato JSON](docs/json-contract.md) | Esquema versionado del inventario |
| [Desarrollo](docs/development.md) | Entorno y comprobaciones |
| [Compilación portable](docs/build.md) | Construir y publicar el ejecutable |
| [Seguridad y permisos](docs/security.md) | Controles y qué se necesita elevar |
| [Pruebas y compatibilidad](docs/testing.md) | Qué se probó y cómo |
| [Limitaciones](docs/limitations.md) | Lo que no hace o no puede garantizar |
| [Decisiones técnicas](docs/decisions.md) | Por qué está construido así |
| [Trabajo pendiente](docs/roadmap.md) | Qué sigue y en qué orden |

## Comprobaciones

```powershell
cd ui
npm ci
npm run check   # formato, ESLint (incluye los límites de capas), tipos y compilación a presentation/web/dist
cd ..
uv sync --frozen
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run mypy
uv run pytest tests/unit tests/integration tests/windows tests/e2e -q
```

Las pruebas e2e y la aplicación sirven la interfaz compilada: sin `npm run build`, la página explica
que falta compilarla.
