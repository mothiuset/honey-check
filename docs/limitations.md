# Limitaciones

## Plataforma

- Solo x64. No se ejecuta en Windows de 32 bits. En ARM64 dependería de la emulación x64, sin probar.
- Necesita Windows PowerShell 5.1 para WMI y paquetes AppX. Sin él quedan solo los programas del
  Registro y las consultas nativas.
- Python 3.12 requiere Windows 8.1 o posterior; solo se apunta a Windows 10 y 11.
- El ejecutable **no está firmado**: SmartScreen, AppLocker, WDAC o un antivirus pueden advertirlo
  o bloquearlo. Se extrae en `%TEMP%`: una directiva que bloquee ejecutar desde ahí puede impedir
  su arranque.

## Software

- Las aplicaciones portables sin registro de instalación **no se detectan**.
- Software por usuario y paquetes AppX: solo los del usuario actual.
- `executablePath` queda en `null` cuando Windows no lo identifica con certeza, algo habitual en
  bibliotecas, runtimes, controladores y productos MSI que no declaran icono ni carpeta.
- Las rutas `probable` pueden ser incorrectas; el nombre del programa solo orienta la elección.
- `DisplayIcon` es lo que declara el fabricante y puede apuntar a un lanzador o componente.
- La arquitectura solo es `verified` si se pudo leer el ejecutable.
- Los paquetes AppX no reportan fecha de instalación ni tamaño, y su firma se informa por paquete.
- La verificación de firmas tiene un presupuesto de tiempo; las restantes quedan `not_checked`.

## Hardware

- Los datos dependen de lo que declare el firmware. En equipos ensamblados, SMBIOS suele traer
  valores de relleno, que se informan como desconocidos.
- `freeSlots` se calcula con lo que declara SMBIOS, que puede no coincidir con las ranuras físicas.
- El fabricante del disco y de la RAM se publica como lo reporta Windows. No se traducen códigos
  JEDEC como `80CE000080CE`.
- Controladoras RAID pueden ocultar los discos físicos. Con `Win32_DiskDrive` no se distingue HDD de
  SSD: se declara incierto.
- Sin el espacio de nombres de almacenamiento no hay particiones ni salud por unidad.
- La salud de batería requiere clases WMI que muchos firmwares no implementan.
- No se lista cada controlador instalado: solo los dispositivos que informan errores.
- La salud de los discos es la que reporta Windows; no se leen atributos SMART.

## USB y ciclo de vida

- Si se retira la USB, Honey Check lo detecta, conserva el análisis en memoria y ofrece otra
  carpeta. **No se garantiza un cierre ordenado tras una extracción física**: Windows puede invalidar
  partes del ejecutable no cargadas. Lo probado es la retirada de una unidad `subst`.
- Ese escenario puede dejar `%TEMP%\_MEI*` si el proceso muere de forma abrupta.
- Instancia única por sesión: otra copia en otra USB abre la interfaz de la primera.
- Desde una USB lenta, la primera apertura puede tardar más porque se extrae el ejecutable.

## Interfaz

- Requiere un navegador predeterminado. Si no se abre, la bandeja lo avisa, pero no hay ventana propia.
- El tipo de letra depende de las fuentes de Windows: en versiones sin Bahnschrift se usa Segoe UI.
- La interfaz está solo en español.

## Alcance

No incluye plataforma web, sincronización, base de datos, reportes PDF o Excel ni diagnósticos de
software. Los inventarios no se cifran.
