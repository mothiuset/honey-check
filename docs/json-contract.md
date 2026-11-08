# Contrato JSON

Esquema formal: [`schema/inventory-1.0.0.schema.json`](../schema/inventory-1.0.0.schema.json). Una
prueba impide que diverja de los modelos de `domain/inventory.py`.

Cada análisis produce un archivo independiente:
`honey-check_<equipo>_<AAAA-MM-DD>_<HHMMSS>.json`, en UTF-8. Si el nombre existe se añade `_01`:
un inventario previo nunca se sobrescribe.

## Versionado

`schema.version` sigue SemVer. Un cambio incompatible sube la versión mayor y añade una migración
en `domain/migrations.py`. Honey Check rechaza documentos de un esquema más reciente que el suyo:
el historial los lista como no legibles, sin fallar.

## Estructura

```jsonc
{
  "schema": { "name": "honey-check.inventory", "version": "1.0.0" },
  "collection": {
    "inventoryId": "uuid", "startedAt": "ISO 8601", "finishedAt": "ISO 8601",
    "durationMs": 0, "appVersion": "0.1.0", "appCommit": "sha", "status": "complete | partial",
    "isElevated": { /* Observed */ }
  },
  "device": { /* identificación, placa, firmware, dominio */ },
  "hardware": {
    "processor": {}, "memory": {}, "storage": {}, "graphics": {},
    "displays": {}, "network": {}, "battery": {}, "tpm": {}
  },
  "operatingSystem": {},
  "software": {},
  "devices": {},
  "security": {},
  "modules": [{ "name": "memory", "status": "ok", "durationMs": 0, "retries": 0 }],
  "warnings": [{ "module": "tpm", "code": "access_denied", "message": "", "source": "" }],
  "errors": []
}
```

Una sección `null` significa que su módulo falló: el motivo está en `modules` y `errors`. `status`
de módulo: `ok`, `partial`, `failed`, `timeout`, `cancelled`.

## Almacenamiento (2.2.0)

`hardware.storage.external` lista los discos USB, tarjetas y FireWire conectados al analizar, con
sus particiones y letras; su `serialNumber` queda desconocido (`external_not_collected`).
`excluded` queda para discos virtuales y de red. `PhysicalDisk.controllerVendor` dice la marca de
la controladora cuando Windows no da la del disco; `manufacturer` puede venir deducido del modelo
(`inferred`, `rule:model_prefix`).

## Periféricos (2.2.0)

`peripherals.devices` tiene un elemento por **aparato físico**, no por nodo de Windows: un teclado
con mouse y teclas multimedia es uno solo, con `functions: ["keyboard", "mouse", "media_keys"]`
y sus nodos en `parts`. Se agrupa por el contenedor que Windows asigna a cada aparato y, para lo
integrado (todo comparte el contenedor del equipo), por el nodo padre. `genericName: true` indica
que Windows solo dio un nombre genérico («I2C HID Device»): la interfaz muestra la función
(«Touchpad integrado»). Categorías nuevas: `touchpad`, `wireless_receiver`, `game_controller`;
conexión nueva: `video` (monitor por cable de video).

`peripherals.disconnected` lista lo que Windows recuerda sin estar conectado: `state: "paired"`
(emparejado por Bluetooth, apagado o lejos) o `"leftover"` (conectado alguna vez y ya no), con la
última vez que se vio, `alsoConnected` si el mismo aparato está conectado ahora en otro puerto y
`driverInfs` con los controladores de terceros a respaldar antes de quitarlo.

Un inventario 2.1.0 se lee igual (los campos nuevos tienen valor por defecto): una fila por función
de Windows y sin lista de no conectados.

## Valores observados

La mayoría de los datos del equipo son un objeto `Observed`:

```json
{ "value": "DDR4", "confidence": "reported",
  "source": "cim:root/cimv2/Win32_PhysicalMemory.SMBIOSMemoryType", "reason": null, "raw": null }
```

| `confidence` | Significado |
| --- | --- |
| `verified` | Comprobado contra el artefacto real (cabecera PE) |
| `reported` | Devuelto por Windows, SMBIOS o el Registro |
| `inferred` | Calculado con una regla determinista |
| `probable` | Candidato heurístico: puede ser incorrecto |
| `unknown` | No determinado: `value` es `null` y `reason` explica por qué |

El modelo impone las reglas: un valor presente exige `source`; un valor nulo exige `reason` y
confianza `unknown`. `raw` conserva el original cuando se descarta, por ejemplo un relleno de
fabricante como `To Be Filled By O.E.M.`.

Códigos de `reason` frecuentes: `not_reported_by_windows`, `placeholder_value`, `access_denied`,
`query_failed`, `not_available_on_this_system`, `invalid_value`, `not_applicable`, `not_resolved`.

## Unidades

Van en el nombre del campo: `capacityBytes`, `speedMts`, `maxFrequencyMhz`, `l3CacheKib`,
`linkSpeedBitsPerSecond`, `widthPixels`, `chargePercent`, `designCapacityMwh`, `durationMs`.

## Software

```jsonc
{
  "id": "16 hex",                // estable entre inventarios; no depende de la versión
  "name": "...",
  "version": {}, "publisher": {},
  "scope": "machine | current_user",
  "installerType": "msi | traditional | msix | other | unknown",
  "mechanism": "registry_uninstall | appx_package",
  "detectionSource": "registry:HKLM\\64\\...",
  "installPath":    { "value": null, "confidence": "unknown", "source": null,
                      "state": "not_provided", "reason": "install_location_not_reported" },
  "executablePath": { "value": "C:\\...\\app.exe", "confidence": "reported",
                      "source": "...DisplayIcon", "state": "valid", "reason": null },
  "uninstall": { "command": "texto, nunca ejecutado", "path": {} },
  "installDate": {}, "architecture": {}, "sizeBytes": {},
  "executable": {
    "fileVersion": "", "productVersion": "", "productName": "", "fileDescription": "",
    "companyName": "", "signature": { "status": "valid", "signer": "CN=...", "reason": null }
  },
  "packageFullName": null, "packageSignatureKind": null,
  "isSystemComponent": false, "isFramework": false, "isUpdate": false
}
```

`state` de una ruta: `valid`, `missing`, `inaccessible`, `not_provided` o `not_checked` (red).

`executablePath` es `null` con un `reason` cuando Windows no lo identifica:
`windows_does_not_identify_executable`, `no_unambiguous_executable_in_install_path`,
`display_icon_is_not_the_main_executable`, `install_path_missing_on_disk`,
`install_path_inaccessible`, `package_manifest_not_readable`, `package_declares_no_executable`.

La arquitectura es `verified` solo si proviene de la cabecera PE. Si se deduce del nombre o de la
vista del Registro es `probable`: la vista refleja al instalador, no al producto.

`software.sources` informa del estado de cada fuente y `software.limitations` de lo que no puede
detectarse. La fecha `lastWriteTime` del Registro se publica como `probable` y no equivale a la
fecha de instalación.

## Datos sensibles

El documento incluye seriales, UUID, nombre del equipo, dominio, MAC, IP y rutas. No incluye
contraseñas, tokens ni claves. Trátelo como información institucional.
