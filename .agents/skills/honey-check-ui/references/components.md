# Componentes de la interfaz

Rutas relativas a `ui/src/presentation/`.

## Compartidos (`shared/components`)

| Componente | Para qué | Notas |
| --- | --- | --- |
| `Button`, `LinkButton` | Acciones. Tonos `primary` (la acción principal), `danger` (elimina o desinstala), `ghost` (secundaria discreta), `default` | Una sola `primary` por pantalla |
| `Tag` | Riesgo de una herramienta, «Consulta otro equipo» | No para estados de resultado: eso es `StatusGlyph` |
| `Notice` | Una negativa del servicio (sesión, cambio en curso) | No para resultados |
| `DataTable` | Tablas con orden, prioridad de columnas por ancho y modo teléfono | Líneas finas, sin marco; cifras con `data-align='end'` |
| `Field` | Etiqueta + control + ayuda | |
| `Lede`, `PathText`, `VisuallyHidden` | Texto de apoyo, rutas, texto solo para lectores de pantalla | |
| `DeviceParts` | Partes de Windows de un aparato (nombre e identificador copiable), plegadas bajo su fila |
| `SpecList`, `Value` | Pares dato/valor del inventario | |
| `Copyable` | Un valor que se copia con un clic (serial, IP, MAC, ruta, cifra); `truncate` `end` o `start` (rutas) y `mono` |

## Soporte (`support/components`)

| Componente | Para qué |
| --- | --- |
| `ToolRunner` | La pantalla de una herramienta: datos, revisión, ejecución y resultado |
| `ToolForm` | Parámetros; oculta los que trajo el enlace (`fixed`) |
| `ConfirmPanel` | Revisión previa: `Plan.summary`, `Plan.checks`, un botón con el título de la herramienta, aviso de administrador, comandos plegados |
| `RunView` | En curso (barra de miel, qué hace ahora, Cancelar) y registro plegado |
| `Verdict` | La frase del resultado según estado y verificaciones (`outcomeOf`) |
| `Readout` | `ToolResult.summary` como lectura de instrumento; valores largos o rutas en línea propia |
| `CheckList` | `Check[]` con `StatusGlyph`, detalle, acción `fix` y `technical` plegado |
| `StatusGlyph` | Celda de panal con marca: ok, warn, fail, info, skipped |
| `SpaceExplorer` | `Chart` tipo `treemap`: nivel por nivel; nodos con `children` se entran, nodos con `actions` se eligen y muestran sus acciones |
| `ShareBars` / `ShareRow` | `Chart` tipo `bar`: reparto plano con barras SVG |
| `ResultTable` | `Table` con búsqueda, selección múltiple y acción masiva; cada celda en `Copyable` |
| `SourcePicker` | Opciones en vivo de un parámetro (`Param.source`: impresoras, unidades), una o varias |
| `ActionButton` | El botón de cualquier acción de Soporte: inmediata, panel o pantalla según la herramienta |
| `ActionLayer` | Panel lateral de un cambio (revisión, avance, resultado) y avisos de lo inmediato; montado una vez en `App` |
| `VersionBar` | De cuándo es el resultado, selector de versiones y «Actualizar» (solo consultas) |
| `Changes` | Qué cambió desde la versión anterior con los mismos datos: cifras y carpetas |

## Contrato con el servidor (`domain/support.py`)

- `ToolResult.summary: Fact[]` → `Readout`. Tono `warn`/`bad` solo si hay algo que mirar.
- `ToolResult.checks: Check[]` → `CheckList`. `detail` en palabras del técnico, `technical` con el
  código, `fix` con la herramienta que lo arregla.
- `Chart` con nodos `{name, value, path?, children?, more?, detail?, actions?, group?, id?}`;
  `actions` se arma con `node_actions(link(...))` y sus `{campo}` se llenan con el nodo.
- `Table.row_actions` y `bulk_action` para tablas.
- `SupportTool(review=...)` devuelve `(resumen, checks, necesita_admin)` para `ConfirmPanel`.
