# Compilación portable

Para usarlo en este equipo basta **`compilar.cmd`** (doble clic, o `.\compilar.cmd
--sin-abrir`), que llama a `tools/build.py --sin-zip`. `build.py` (también lo usa `publish.py`)
protege `dist\HoneyCheck`:

- **Una sola compilación a la vez** (bloqueo en `build\compilando.lock`, que Windows suelta si el
  proceso termina): dos a la vez se pisaban la carpeta y la dejaban vacía.
- **Nada se toca con la app abierta desde ahí**: se detecta porque su `.exe` no se puede abrir para
  escritura. Antes, PyInstaller borraba la carpeta a medias y la app abierta quedaba rota.
- **PyInstaller compila en `build\salida`**; solo si sale bien se cambia el contenido de
  `dist\HoneyCheck` archivo por archivo. La carpeta misma no se renombra (una ventana del Explorador
  o una terminal ubicada en ella lo impiden). Si algo falla, `dist\HoneyCheck` queda como estaba.
- **`HoneyCheck-datos` no se mueve nunca**, y el zip y `SHA256SUMS.txt` se hacen antes, sin datos.

Los pasos por separado:

```powershell
uv sync --frozen
uv run python tools/build.py   # compila antes la interfaz (npm ci si falta, npm run build)
uv run python tools/build.py --sin-zip   # en local: sin HoneyCheck.zip, unos segundos menos
$env:HONEY_CHECK_EXE = "$PWD\dist\HoneyCheck\HoneyCheck.exe"
uv run pytest tests/packaging
```

Genera en `dist/`, sin versionar:

| Archivo | Contenido |
| --- | --- |
| `HoneyCheck\HoneyCheck.exe` | Ejecutable sin consola, con el código y la interfaz dentro; pide elevación solo si el técnico la solicita |
| `HoneyCheck\componentes\` | Python, extensiones, DLL y el icono: se cargan desde aquí, sin descomprimir en el equipo |
| `HoneyCheck\componentes\huella-componentes.txt` | Huella de `componentes\`; el `.exe` la compara al arrancar |
| `HoneyCheck\SHA256SUMS.txt` | Hash de cada archivo de la carpeta |
| `HoneyCheck.zip` | La carpeta completa, lista para copiar a la USB |
| `HoneyCheck.exe.sha256` | Hash del ejecutable |
| `build-manifest.json` | Versión, número de compilación, commit, si había cambios sin commit, versión del esquema, fecha, hash, tamaño y huella de `componentes\` |
| `THIRD_PARTY_LICENSES.txt` | Licencias de lo incluido; debe distribuirse junto al ejecutable |

La construcción se detiene si una dependencia de ejecución (Python o npm) tiene licencia copyleft, no
declara licencia o es de telemetría (`tools/licenses.py`). GSAP usa la licencia «Standard no-charge»
de GSAP/Webflow: no es copyleft ni OSI, y queda listada en el aviso a terceros.

`tests/packaging` ejecuta de verdad el `.exe` en este equipo: arranque, recursos de la interfaz,
instancia única, análisis, salida limpia, retirada de la unidad y rechazo de unos `componentes\`
de otra compilación.

## Número de compilación

`tools/build.py` escribe en el `.exe` (`honey_check._build_info`, sin versionar) el número de compilación (`git rev-list --count HEAD`: siempre sube), el commit, la fecha y si había cambios sin commit en `la carpeta del proyecto`. La app lo muestra en el menú lateral («Versión 0.2.0 · compilación 676 · 2a16530 · 2026-11-07») y `tools/publish.py` lo pone en el título de la página de descarga: así se compara de un vistazo si una copia es la última. La app no consulta internet para saberlo.

## Actualizar solo el ejecutable

El código Python y la interfaz compilada viajan dentro de `HoneyCheck.exe`. La interfaz va como un
zip en memoria (`honey_check._bundle`, que genera `packaging/honey-check.spec`) y se sirve desde ahí
sin escribir nada en disco. `componentes\` solo cambia si cambian Python, una extensión, una DLL o
el icono. Su huella (SHA-256 de cada archivo menos `base_library.zip`, que se regenera con el mismo
contenido, más la versión de Python) queda en el `.exe` y en `huella-componentes.txt`.

Dos compilaciones con las mismas dependencias tienen la misma huella: basta copiar el `.exe` nuevo
sobre la carpeta. Si no coinciden, `packaging/entrypoint.py` muestra un aviso y sale con el código 3
antes de cargar nada más; con `--status-file` (pruebas) escribe `{"error": "components_mismatch"}`
en lugar del aviso.

## Publicar una compilación

Las descargas no dependen de GitHub Actions (en un repositorio privado consume minutos pagos). Se
compilan, se prueban y se suben desde el equipo del desarrollador; subir archivos a una Release no
cuesta nada:

```powershell
cd la carpeta del proyecto
uv run python tools/publish.py               # compila, prueba el .exe y publica
uv run python tools/publish.py --sin-pruebas # si Honey Check está abierto en este equipo
```

`tools/publish.py` solo publica un commit que ya está en GitHub y sin cambios locales. Compila
(interfaz incluida), corre `tests/packaging` contra el `.exe` y reemplaza en la versión preliminar
[`honey-check-latest`](https://github.com/mothiuset/honey-check/releases/tag/honey-check-latest):
`HoneyCheck.exe`, `HoneyCheck.exe.sha256`, `build-manifest.json` y `HoneyCheck-experimental.zip`
(con su `.sha256`). Las notas dicen el commit, los hashes y, comparando la huella de
`componentes\` con la publicada antes, si basta el `.exe` o hace falta el zip. Necesita `uv`,
Node.js (npm) y GitHub CLI (`gh`) con sesión iniciada.

Para compilar sin publicar: `uv run python tools/build.py` (o `--sin-zip`); el resultado queda en
`dist\HoneyCheck\`.

`.github/workflows/honey-check.yml` ya no corre en cada push: queda para lanzarlo a mano desde la
pestaña Actions si se quiere la verificación en los runners de GitHub (pruebas en `windows-2022` y
`windows-2025` y el `.exe` probado en otro Windows).

El repositorio es privado: el zip, los artefactos y las versiones requieren una cuenta con acceso.

```powershell
gh run download <run-id> -R mothiuset/honey-check -n honey-check-<sha>
gh release download <etiqueta> -R mothiuset/honey-check -p "HoneyCheck.exe*"
```

Compruebe el hash antes de copiarlo a una USB:

```powershell
Get-FileHash .\HoneyCheck.exe -Algorithm SHA256
Get-Content .\HoneyCheck.exe.sha256
```

## Firma de código

El ejecutable **no está firmado**: no hay un certificado disponible. SmartScreen puede advertirlo
y AppLocker o WDAC pueden bloquearlo. Para un despliegue institucional hace falta firmarlo o que
el administrador lo autorice por hash.
